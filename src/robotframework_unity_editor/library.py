"""Robot Framework library for Unity Editor automation on Windows."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import win32con
import win32gui
import win32process
from PIL import ImageGrab
from pywinauto import Application, keyboard, mouse
from robot.api import logger
from robot.api.deco import keyword, library

from .bridge_script import UNITY_EDITOR_BRIDGE_SCRIPT

DEFAULT_WINDOW_BACKEND = "uia"
DEFAULT_STARTUP_TIMEOUT_SECONDS = 420
DEFAULT_STABILITY_TIMEOUT_SECONDS = 60
DEFAULT_BOX_WIDTH = 180
DEFAULT_BOX_HEIGHT = 48
DEFAULT_UNITY_BRIDGE_HOST = "127.0.0.1"
DEFAULT_UNITY_BRIDGE_PORT = 39067
DEFAULT_UNITY_BRIDGE_PACKAGE_NAME = "com.metyatech.unity-automation-bridge"
DEFAULT_UNITY_BRIDGE_PACKAGE_URL = (
    "https://github.com/metyatech/robotframework-unity-editor.git?path=/unity-package#main"
)
UNITY_BRIDGE_SCRIPT_RELATIVE_PATH = Path("Assets/Editor/RobotFrameworkUnityBridge.cs")
UNITY_MANIFEST_RELATIVE_PATH = Path("Packages/manifest.json")

KEY_ALIASES = {
    "ENTER": "{ENTER}",
    "ESC": "{ESC}",
    "ESCAPE": "{ESC}",
    "TAB": "{TAB}",
    "SPACE": " ",
    "DELETE": "{DELETE}",
    "BACKSPACE": "{BACKSPACE}",
    "UP": "{UP}",
    "DOWN": "{DOWN}",
    "LEFT": "{LEFT}",
    "RIGHT": "{RIGHT}",
    "HOME": "{HOME}",
    "END": "{END}",
    "PAGEUP": "{PGUP}",
    "PAGEDOWN": "{PGDN}",
    "F1": "{F1}",
    "F2": "{F2}",
    "F3": "{F3}",
    "F4": "{F4}",
    "F5": "{F5}",
    "F6": "{F6}",
    "F7": "{F7}",
    "F8": "{F8}",
    "F9": "{F9}",
    "F10": "{F10}",
    "F11": "{F11}",
    "F12": "{F12}",
}

MODIFIER_ALIASES = {
    "CTRL": "^",
    "CONTROL": "^",
    "ALT": "%",
    "SHIFT": "+",
    "WIN": "#",
    "WINDOWS": "#",
}


def clamp_ratio(value: float) -> float:
    """Clamp ratios to [0, 1] so Robot callers can pass slightly out-of-range values."""
    return max(0.0, min(1.0, value))


def build_click_annotation(x: int, y: int, width: int, height: int) -> dict[str, Any]:
    return {
        "type": "click",
        "box": {
            "x": x - round(width / 2),
            "y": y - round(height / 2),
            "width": width,
            "height": height,
        },
    }


def build_drag_annotation(from_x: int, from_y: int, to_x: int, to_y: int) -> dict[str, Any]:
    return {
        "type": "dragDrop",
        "from": {"x": from_x, "y": from_y},
        "to": {"x": to_x, "y": to_y},
    }


def normalize_hierarchy_path(value: str) -> str:
    normalized = str(value or "").replace("\\", "/").strip()
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return normalized.strip("/")


def build_hierarchy_select_annotation(hierarchy_path: str) -> dict[str, Any]:
    return {
        "type": "hierarchySelect",
        "hierarchyPath": normalize_hierarchy_path(hierarchy_path),
    }


def ensure_upm_dependency_in_manifest(
    manifest: dict[str, Any],
    package_name: str,
    package_url: str,
) -> bool:
    dependencies = manifest.setdefault("dependencies", {})
    if not isinstance(dependencies, dict):
        raise ValueError("manifest.json dependencies must be a JSON object.")
    current = dependencies.get(package_name)
    if str(current or "").strip() != "":
        return False
    dependencies[package_name] = package_url
    return True


def remove_legacy_bridge_script(project_root: Path) -> bool:
    changed = False
    script_path = project_root / UNITY_BRIDGE_SCRIPT_RELATIVE_PATH
    for path in (script_path, Path(f"{script_path}.meta")):
        if not path.exists():
            continue
        path.unlink()
        changed = True
    return changed


def shortcut_to_send_keys(shortcut: str) -> str:
    tokens = [token.strip().upper() for token in shortcut.split("+") if token.strip()]
    if not tokens:
        raise ValueError("Shortcut cannot be empty.")

    modifiers: list[str] = []
    key_token: str | None = None
    for token in tokens:
        modifier = MODIFIER_ALIASES.get(token)
        if modifier is not None:
            modifiers.append(modifier)
            continue
        key_token = token

    if key_token is None:
        raise ValueError(f"Shortcut must contain a non-modifier key: {shortcut}")

    if len(key_token) == 1:
        key_part = key_token.lower()
    else:
        key_part = KEY_ALIASES.get(key_token, f"{{{key_token}}}")

    return "".join(modifiers) + key_part


def find_unity_executable(
    explicit_path: str | None = None,
    env_path: str | None = None,
    candidate_paths: Sequence[Path] | None = None,
) -> Path:
    if explicit_path:
        path = Path(explicit_path).expanduser().resolve()
        if path.exists():
            return path
        raise FileNotFoundError(f"Unity executable was not found: {path}")

    from_env = env_path or os.environ.get("UNITY_EDITOR_EXE")
    if from_env:
        path = Path(from_env).expanduser().resolve()
        if path.exists():
            return path
        raise FileNotFoundError(f"UNITY_EDITOR_EXE does not exist: {path}")

    candidates = list(candidate_paths or [])
    if not candidates:
        hub_root = Path(r"C:\Program Files\Unity\Hub\Editor")
        if hub_root.exists():
            candidates.extend(sorted(hub_root.glob("*/Editor/Unity.exe"), reverse=True))
        direct = Path(r"C:\Program Files\Unity\Editor\Unity.exe")
        candidates.append(direct)

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    raise FileNotFoundError("Could not locate Unity.exe. Set UNITY_EDITOR_EXE or pass unity_exe.")


def _normalize_window_hint(window_hint: str | None) -> str:
    hint = (window_hint or "Unity").strip()
    return hint if hint else "Unity"


def title_matches_window_hint(title: str, window_hint: str | None) -> bool:
    normalized_hint = _normalize_window_hint(window_hint).lower()
    normalized_title = title.strip().lower()
    if not normalized_title:
        return False
    return normalized_hint in normalized_title


def pick_unity_window_handle(
    candidates: Sequence[tuple[int, str]],
    window_hint: str | None,
    foreground_handle: int | None = None,
) -> int | None:
    title_by_handle = {
        handle: title
        for handle, title in candidates
        if title_matches_window_hint(title, window_hint)
    }
    if foreground_handle is not None and foreground_handle in title_by_handle:
        return foreground_handle
    for handle, _ in candidates:
        if handle in title_by_handle:
            return handle
    return None


@library(scope="GLOBAL", auto_keywords=False)
class UnityEditorLibrary:
    """Robot Framework keywords for Unity Editor GUI automation on Windows."""

    def __init__(
        self,
        output_dir: str | None = None,
        backend: str = DEFAULT_WINDOW_BACKEND,
        default_startup_timeout_seconds: int = DEFAULT_STARTUP_TIMEOUT_SECONDS,
        unity_bridge_host: str = DEFAULT_UNITY_BRIDGE_HOST,
        unity_bridge_port: int = DEFAULT_UNITY_BRIDGE_PORT,
    ) -> None:
        self._require_windows()
        self._output_dir = Path(output_dir).resolve() if output_dir else Path.cwd()
        self._backend = backend
        self._default_startup_timeout_seconds = default_startup_timeout_seconds
        self._unity_bridge_host = str(unity_bridge_host).strip() or DEFAULT_UNITY_BRIDGE_HOST
        self._unity_bridge_port = int(unity_bridge_port)
        self._unity_process: subprocess.Popen[bytes] | None = None
        self._unity_pid: int | None = None
        self._app: Any = None
        self._window: Any = None

    @keyword("Set Unity Output Directory")
    def set_unity_output_directory(self, output_dir: str) -> str:
        self._output_dir = Path(output_dir).resolve()
        self._output_dir.mkdir(parents=True, exist_ok=True)
        return str(self._output_dir)

    @keyword("Get Unity Output Directory")
    def get_unity_output_directory(self) -> str:
        return str(self._output_dir)

    @keyword("Resolve Unity Executable")
    def resolve_unity_executable(self, unity_exe: str | None = None) -> str:
        return str(find_unity_executable(unity_exe))

    @keyword("Set Unity Bridge Endpoint")
    def set_unity_bridge_endpoint(
        self,
        host: str = DEFAULT_UNITY_BRIDGE_HOST,
        port: int = DEFAULT_UNITY_BRIDGE_PORT,
    ) -> str:
        self._unity_bridge_host = str(host).strip() or DEFAULT_UNITY_BRIDGE_HOST
        self._unity_bridge_port = int(port)
        return self.get_unity_bridge_endpoint()

    @keyword("Get Unity Bridge Endpoint")
    def get_unity_bridge_endpoint(self) -> str:
        return f"http://{self._unity_bridge_host}:{self._unity_bridge_port}"

    @keyword("Install Unity Editor Bridge Script")
    def install_unity_editor_bridge_script(self, project_path: str) -> str:
        project_root = Path(project_path).resolve()
        bridge_path = project_root / UNITY_BRIDGE_SCRIPT_RELATIVE_PATH
        bridge_path.parent.mkdir(parents=True, exist_ok=True)
        bridge_path.write_text(UNITY_EDITOR_BRIDGE_SCRIPT, encoding="utf-8")
        logger.info(f"Installed Unity bridge script: {bridge_path}")
        return str(bridge_path)

    @keyword("Ensure Unity Bridge UPM Package")
    def ensure_unity_bridge_upm_package(
        self,
        project_path: str,
        package_name: str = DEFAULT_UNITY_BRIDGE_PACKAGE_NAME,
        package_url: str = DEFAULT_UNITY_BRIDGE_PACKAGE_URL,
    ) -> bool:
        project_root = Path(project_path).resolve()
        manifest_path = project_root / UNITY_MANIFEST_RELATIVE_PATH
        if not manifest_path.exists():
            raise FileNotFoundError(
                f"Unity manifest.json not found: {manifest_path}. "
                "Expected a valid Unity project path."
            )
        raw = manifest_path.read_text(encoding="utf-8")
        manifest_data = json.loads(raw or "{}")
        if not isinstance(manifest_data, dict):
            raise ValueError("manifest.json root must be a JSON object.")

        changed = ensure_upm_dependency_in_manifest(
            manifest_data,
            package_name=package_name,
            package_url=package_url,
        )
        legacy_changed = remove_legacy_bridge_script(project_root)
        if changed:
            manifest_path.write_text(
                json.dumps(manifest_data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            logger.info(f"Added UPM dependency '{package_name}' to {manifest_path}")
        if legacy_changed:
            legacy_script_path = project_root / UNITY_BRIDGE_SCRIPT_RELATIVE_PATH
            logger.info(f"Removed legacy bridge script at {legacy_script_path}")
        return changed or legacy_changed

    @keyword("Start Unity Editor")
    def start_unity_editor(
        self,
        unity_exe: str | None = None,
        project_path: str | None = None,
        startup_timeout_seconds: int | None = None,
        create_project_if_missing: bool = True,
        extra_args: str | None = None,
    ) -> int:
        unity_path = find_unity_executable(unity_exe)
        resolved_project = (
            Path(project_path).resolve()
            if project_path
            else (self._output_dir / "unity-sample-project").resolve()
        )

        if create_project_if_missing:
            self._ensure_project_exists(unity_path, resolved_project)

        command = [str(unity_path), "-projectPath", str(resolved_project)]
        if extra_args:
            command.extend(extra_args.split())

        logger.info(f"Starting Unity Editor: {' '.join(command)}")
        self._unity_process = subprocess.Popen(command)
        self._unity_pid = self._unity_process.pid
        timeout_seconds = startup_timeout_seconds or self._default_startup_timeout_seconds
        self.connect_unity_editor(self._unity_pid, timeout_seconds)
        self.ensure_unity_window_stable(timeout_seconds=min(timeout_seconds, 90))
        return self._unity_pid

    @keyword("Connect Unity Editor")
    def connect_unity_editor(
        self,
        process_id: int | None = None,
        timeout_seconds: int = DEFAULT_STABILITY_TIMEOUT_SECONDS,
    ) -> int:
        unity_pid = process_id or self._unity_pid
        if unity_pid is None:
            raise RuntimeError("Unity process id is not set. Start Unity first.")

        deadline = time.time() + timeout_seconds
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                app = Application(backend=self._backend).connect(process=unity_pid)
                window = app.top_window()
                if window.exists() and window.is_visible():
                    self._app = app
                    self._window = window
                    self._unity_pid = unity_pid
                    return unity_pid
            except Exception as error:  # pragma: no cover - integration path
                last_error = error
            time.sleep(1)

        if last_error is not None:
            raise RuntimeError(f"Failed to connect Unity window: {last_error}") from last_error
        raise RuntimeError("Failed to connect Unity window before timeout.")

    @keyword("Attach To Running Unity Editor")
    def attach_to_running_unity_editor(
        self,
        window_hint: str = "Unity",
        timeout_seconds: int = DEFAULT_STABILITY_TIMEOUT_SECONDS,
    ) -> int:
        deadline = time.time() + timeout_seconds
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                matched_handle = pick_unity_window_handle(
                    candidates=self._enumerate_visible_windows(),
                    window_hint=window_hint,
                    foreground_handle=win32gui.GetForegroundWindow(),
                )
                if matched_handle is None:
                    time.sleep(0.5)
                    continue

                _, unity_pid = win32process.GetWindowThreadProcessId(matched_handle)
                app = Application(backend=self._backend).connect(handle=matched_handle)
                window = app.window(handle=matched_handle)
                if not window.exists() or not window.is_visible():
                    raise RuntimeError("Matched Unity window is not visible.")

                self._app = app
                self._window = window
                self._unity_pid = unity_pid
                self._unity_process = None
                return unity_pid
            except Exception as error:  # pragma: no cover - integration path
                last_error = error
            time.sleep(0.5)

        if last_error is not None:
            raise RuntimeError(
                f"Failed to attach running Unity window: {last_error}"
            ) from last_error
        raise RuntimeError("Failed to attach running Unity window before timeout.")

    @keyword("Ensure Unity Window Stable")
    def ensure_unity_window_stable(
        self,
        timeout_seconds: int = DEFAULT_STABILITY_TIMEOUT_SECONDS,
        min_width: int = 320,
        min_height: int = 240,
    ) -> dict[str, int]:
        deadline = time.time() + timeout_seconds
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                self._refresh_window()
                window = self._require_window()
                rect = window.rectangle()
                width = int(rect.right - rect.left)
                height = int(rect.bottom - rect.top)
                if width >= min_width and height >= min_height:
                    return self.get_unity_window_rect()
            except Exception as error:  # pragma: no cover - integration path
                last_error = error
            time.sleep(0.7)

        if last_error is not None:
            raise RuntimeError(f"Unity window did not stabilize: {last_error}") from last_error
        raise RuntimeError("Unity window did not stabilize before timeout.")

    @keyword("Focus Unity Window")
    def focus_unity_window(self) -> None:
        last_error: Exception | None = None
        for _ in range(3):
            try:
                self._refresh_window()
                window = self._require_window()
                window.set_focus()
                return
            except Exception as error:  # pragma: no cover - integration path
                last_error = error
                try:
                    self._refresh_window()
                    window = self._require_window()
                    rect = window.rectangle()
                    mouse.click(coords=(int(rect.left + 32), int(rect.top + 16)))
                    return
                except Exception as retry_error:
                    last_error = retry_error
                    time.sleep(0.2)

        raise RuntimeError(f"Failed to focus Unity window: {last_error}") from last_error

    @keyword("Maximize Unity Window")
    def maximize_unity_window(self) -> None:
        last_error: Exception | None = None
        window: Any | None = None
        for _ in range(3):
            try:
                self._refresh_window()
                window = self._require_window()
                if window is None:
                    raise RuntimeError("Unity window is unavailable.")
                window.maximize()
                time.sleep(0.3)
                return
            except Exception as error:  # pragma: no cover - integration path
                last_error = error
                try:
                    if window is None:
                        raise RuntimeError("Unity window handle is unavailable.")
                    handle = int(window.handle)
                    win32gui.ShowWindow(handle, win32con.SW_MAXIMIZE)
                    win32gui.SetForegroundWindow(handle)
                    time.sleep(0.3)
                    return
                except Exception as fallback_error:
                    last_error = fallback_error
                time.sleep(0.2)

        raise RuntimeError(f"Failed to maximize Unity window: {last_error}") from last_error

    @keyword("Get Unity Window Rect")
    def get_unity_window_rect(self) -> dict[str, int]:
        window = self._require_window()
        rect = window.rectangle()
        left = int(rect.left)
        top = int(rect.top)
        right = int(rect.right)
        bottom = int(rect.bottom)
        return {
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom,
            "width": right - left,
            "height": bottom - top,
        }

    @keyword("Get Unity Process Id")
    def get_unity_process_id(self) -> int:
        if self._unity_pid is None:
            raise RuntimeError("Unity process id is not set.")
        return self._unity_pid

    @keyword("Click Unity Relative")
    def click_unity_relative(
        self,
        x_ratio: float,
        y_ratio: float,
        button: str = "left",
        box_width: int = DEFAULT_BOX_WIDTH,
        box_height: int = DEFAULT_BOX_HEIGHT,
    ) -> dict[str, Any]:
        x, y, _ = self._relative_point(x_ratio, y_ratio)
        mouse.click(button=button, coords=(x, y))
        return build_click_annotation(x, y, box_width, box_height)

    @keyword("Double Click Unity Relative")
    def double_click_unity_relative(
        self,
        x_ratio: float,
        y_ratio: float,
        box_width: int = DEFAULT_BOX_WIDTH,
        box_height: int = DEFAULT_BOX_HEIGHT,
    ) -> dict[str, Any]:
        x, y, _ = self._relative_point(x_ratio, y_ratio)
        mouse.double_click(coords=(x, y))
        return build_click_annotation(x, y, box_width, box_height)

    @keyword("Right Click Unity Relative")
    def right_click_unity_relative(
        self,
        x_ratio: float,
        y_ratio: float,
        box_width: int = DEFAULT_BOX_WIDTH,
        box_height: int = DEFAULT_BOX_HEIGHT,
    ) -> dict[str, Any]:
        return self.click_unity_relative(
            x_ratio=x_ratio,
            y_ratio=y_ratio,
            button="right",
            box_width=box_width,
            box_height=box_height,
        )

    @keyword("Drag Unity Relative")
    def drag_unity_relative(
        self,
        from_x_ratio: float,
        from_y_ratio: float,
        to_x_ratio: float,
        to_y_ratio: float,
        hold_seconds: float = 0.15,
    ) -> dict[str, Any]:
        from_x, from_y, _ = self._relative_point(from_x_ratio, from_y_ratio)
        to_x, to_y, _ = self._relative_point(to_x_ratio, to_y_ratio)
        mouse.press(coords=(from_x, from_y))
        time.sleep(max(0.0, hold_seconds))
        mouse.move(coords=(to_x, to_y))
        time.sleep(0.1)
        mouse.release(coords=(to_x, to_y))
        return build_drag_annotation(from_x, from_y, to_x, to_y)

    @keyword("Press Unity Keys")
    def press_unity_keys(self, keys: str, pause_seconds: float = 0.03) -> None:
        self.focus_unity_window()
        keyboard.send_keys(keys, pause=pause_seconds, with_spaces=True)

    @keyword("Type Unity Text")
    def type_unity_text(self, text: str, pause_seconds: float = 0.01) -> None:
        self.focus_unity_window()
        keyboard.send_keys(text, with_spaces=True, pause=pause_seconds)

    @keyword("Send Unity Shortcut")
    def send_unity_shortcut(self, shortcut: str) -> str:
        keys = shortcut_to_send_keys(shortcut)
        self.focus_unity_window()
        keyboard.send_keys(keys)
        return keys

    @keyword("Open Unity Top Menu")
    def open_unity_top_menu(self, menu_path: str) -> None:
        window = self._require_window()
        normalized_path = menu_path.replace("/", ">")
        try:
            window.menu_select(normalized_path.replace(">", "->"))
            return
        except Exception:
            self.focus_unity_window()
            tokens = [token.strip() for token in normalized_path.split(">") if token.strip()]
            if not tokens:
                raise ValueError("menu_path cannot be empty.") from None
            keyboard.send_keys("%")
            time.sleep(0.08)
            for token in tokens:
                keyboard.send_keys(token[0].lower())
                time.sleep(0.08)

    @keyword("Wait For Unity Element")
    def wait_for_unity_element(
        self,
        title: str | None = None,
        automation_id: str | None = None,
        class_name: str | None = None,
        control_type: str | None = None,
        index: int | None = None,
        timeout_seconds: float = 10.0,
    ) -> bool:
        self._find_element(
            title=title,
            automation_id=automation_id,
            class_name=class_name,
            control_type=control_type,
            index=index,
            timeout_seconds=timeout_seconds,
        )
        return True

    @keyword("Get Unity Element Rect")
    def get_unity_element_rect(
        self,
        title: str | None = None,
        automation_id: str | None = None,
        class_name: str | None = None,
        control_type: str | None = None,
        index: int | None = None,
        timeout_seconds: float = 10.0,
    ) -> dict[str, int]:
        element = self._find_element(
            title=title,
            automation_id=automation_id,
            class_name=class_name,
            control_type=control_type,
            index=index,
            timeout_seconds=timeout_seconds,
        )
        rect = element.rectangle()
        return {
            "left": int(rect.left),
            "top": int(rect.top),
            "right": int(rect.right),
            "bottom": int(rect.bottom),
            "width": int(rect.right - rect.left),
            "height": int(rect.bottom - rect.top),
        }

    @keyword("Click Unity Element")
    def click_unity_element(
        self,
        title: str | None = None,
        automation_id: str | None = None,
        class_name: str | None = None,
        control_type: str | None = None,
        index: int | None = None,
        button: str = "left",
        timeout_seconds: float = 10.0,
    ) -> dict[str, Any]:
        rect = self.get_unity_element_rect(
            title=title,
            automation_id=automation_id,
            class_name=class_name,
            control_type=control_type,
            index=index,
            timeout_seconds=timeout_seconds,
        )
        x = rect["left"] + round(rect["width"] / 2)
        y = rect["top"] + round(rect["height"] / 2)
        mouse.click(button=button, coords=(x, y))
        return build_click_annotation(
            x=x,
            y=y,
            width=rect["width"],
            height=rect["height"],
        )

    @keyword("Drag Unity Element To Element")
    def drag_unity_element_to_element(
        self,
        source_title: str | None = None,
        source_automation_id: str | None = None,
        target_title: str | None = None,
        target_automation_id: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> dict[str, Any]:
        source = self.get_unity_element_rect(
            title=source_title,
            automation_id=source_automation_id,
            timeout_seconds=timeout_seconds,
        )
        target = self.get_unity_element_rect(
            title=target_title,
            automation_id=target_automation_id,
            timeout_seconds=timeout_seconds,
        )
        from_x = source["left"] + round(source["width"] / 2)
        from_y = source["top"] + round(source["height"] / 2)
        to_x = target["left"] + round(target["width"] / 2)
        to_y = target["top"] + round(target["height"] / 2)
        mouse.press(coords=(from_x, from_y))
        time.sleep(0.1)
        mouse.move(coords=(to_x, to_y))
        time.sleep(0.1)
        mouse.release(coords=(to_x, to_y))
        return build_drag_annotation(from_x, from_y, to_x, to_y)

    @keyword("Get Unity Selected Hierarchy Path")
    def get_unity_selected_hierarchy_path(self, timeout_seconds: float = 2.0) -> str:
        payload = self._request_unity_bridge(
            "GET", "/v1/selection", timeout_seconds=timeout_seconds
        )
        if not bool(payload.get("ok", False)):
            raise RuntimeError(f"Unity bridge selection request failed: {payload}")
        hierarchy_path = normalize_hierarchy_path(str(payload.get("hierarchy_path") or ""))
        return hierarchy_path

    @keyword("Select Unity Hierarchy Object")
    def select_unity_hierarchy_object(
        self,
        hierarchy_path: str,
        timeout_seconds: float = 4.0,
    ) -> dict[str, Any]:
        normalized = normalize_hierarchy_path(hierarchy_path)
        if normalized == "":
            raise ValueError("hierarchy_path cannot be empty.")
        payload = self._request_unity_bridge(
            "POST",
            "/v1/select",
            payload={"hierarchy_path": normalized},
            timeout_seconds=timeout_seconds,
        )
        if not bool(payload.get("ok", False)):
            raise RuntimeError(f"Unity bridge selection failed: {payload}")
        selected = normalize_hierarchy_path(str(payload.get("hierarchy_path") or normalized))
        return build_hierarchy_select_annotation(selected or normalized)

    @keyword("Capture Unity Screenshot")
    def capture_unity_screenshot(self, image_path: str | None = None) -> str:
        rect = self.get_unity_window_rect()
        screenshots_dir = self._output_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        path = (
            Path(image_path).resolve()
            if image_path
            else screenshots_dir / f"unity-{int(time.time() * 1000)}.png"
        )
        image = ImageGrab.grab(
            (rect["left"], rect["top"], rect["right"], rect["bottom"]),
            all_screens=True,
        )
        image.save(path)
        return str(path)

    @keyword("Emit DOCMETA")
    def emit_docmeta(self, metadata: Mapping[str, Any] | str) -> str:
        if isinstance(metadata, str):
            payload = metadata
            if not payload.strip().startswith("{"):
                raise ValueError("String metadata must be JSON text.")
        else:
            payload = json.dumps(dict(metadata), ensure_ascii=False)
        logger.info(f"DOCMETA:{payload}")
        return payload

    @keyword("Emit Click DOCMETA")
    def emit_click_docmeta(self, x: int, y: int, width: int, height: int) -> str:
        metadata = {"annotation": build_click_annotation(x, y, width, height)}
        return self.emit_docmeta(metadata)

    @keyword("Emit Drag DOCMETA")
    def emit_drag_docmeta(self, from_x: int, from_y: int, to_x: int, to_y: int) -> str:
        metadata = {"annotation": build_drag_annotation(from_x, from_y, to_x, to_y)}
        return self.emit_docmeta(metadata)

    @keyword("Stop Unity Editor")
    def stop_unity_editor(self, force_kill: bool = True) -> None:
        unity_pid = self._unity_pid
        process = self._unity_process

        if process and process.poll() is None:
            if force_kill:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                process.terminate()
                process.wait(timeout=15)
        elif unity_pid and force_kill:
            subprocess.run(
                ["taskkill", "/PID", str(unity_pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        self._unity_process = None
        self._unity_pid = None
        self._app = None
        self._window = None

    @keyword("Wait For Seconds")
    def wait_for_seconds(self, seconds: float) -> None:
        time.sleep(max(0.0, seconds))

    def _require_window(self) -> Any:
        if self._window is None:
            raise RuntimeError("Unity window is not connected. Start or connect Unity first.")
        return self._window

    def _refresh_window(self) -> None:
        if self._unity_pid is None:
            return
        self.connect_unity_editor(process_id=self._unity_pid, timeout_seconds=5)

    def _enumerate_visible_windows(self) -> list[tuple[int, str]]:
        windows: list[tuple[int, str]] = []

        def _callback(handle: int, _lparam: int) -> bool:
            if not win32gui.IsWindowVisible(handle):
                return True
            title = win32gui.GetWindowText(handle)
            if not title:
                return True
            windows.append((handle, title))
            return True

        win32gui.EnumWindows(_callback, 0)
        return windows

    def _relative_point(self, x_ratio: float, y_ratio: float) -> tuple[int, int, dict[str, int]]:
        rect = self.get_unity_window_rect()
        x = rect["left"] + round(rect["width"] * clamp_ratio(float(x_ratio)))
        y = rect["top"] + round(rect["height"] * clamp_ratio(float(y_ratio)))
        return x, y, rect

    def _request_unity_bridge(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        timeout_seconds: float = 2.0,
    ) -> dict[str, Any]:
        endpoint = f"{self.get_unity_bridge_endpoint()}{path}"
        data: bytes | None = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = urllib.request.Request(
            endpoint,
            data=data,
            headers=headers,
            method=method.upper(),
        )
        try:
            with urllib.request.urlopen(
                request, timeout=max(0.1, float(timeout_seconds))
            ) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8")
            if raw.strip():
                try:
                    payload_json = json.loads(raw)
                    if isinstance(payload_json, dict):
                        return payload_json
                except json.JSONDecodeError:
                    pass
            raise RuntimeError(
                f"Unity bridge HTTP error: status={error.code} path={path}"
            ) from error
        except urllib.error.URLError as error:
            raise RuntimeError(
                f"Unity bridge is not reachable at {self.get_unity_bridge_endpoint()}."
            ) from error

        try:
            payload_json = json.loads(body or "{}")
        except json.JSONDecodeError as error:
            raise RuntimeError("Unity bridge returned invalid JSON response.") from error
        if not isinstance(payload_json, dict):
            raise RuntimeError("Unity bridge returned unexpected response payload.")
        return payload_json

    def _find_element(
        self,
        title: str | None = None,
        automation_id: str | None = None,
        class_name: str | None = None,
        control_type: str | None = None,
        index: int | None = None,
        timeout_seconds: float = 10.0,
    ) -> Any:
        window = self._require_window()
        criteria: dict[str, Any] = {}
        if title is not None:
            criteria["title"] = title
        if automation_id is not None:
            criteria["auto_id"] = automation_id
        if class_name is not None:
            criteria["class_name"] = class_name
        if control_type is not None:
            criteria["control_type"] = control_type
        if index is not None:
            criteria["found_index"] = index

        if not criteria:
            raise ValueError(
                "At least one selector is required: "
                "title, automation_id, class_name, or control_type."
            )

        deadline = time.time() + timeout_seconds
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                candidate = window.child_window(**criteria)
                wrapper = candidate.wrapper_object()
                return wrapper
            except Exception as error:
                last_error = error
            time.sleep(0.2)

        raise RuntimeError(
            f"Unity element was not found with criteria={criteria}. "
            f"Last error={last_error if last_error else 'none'}"
        )

    def _ensure_project_exists(self, unity_exe: Path, project_path: Path) -> None:
        if (project_path / "ProjectSettings").exists():
            return

        project_path.mkdir(parents=True, exist_ok=True)
        log_path = self._output_dir / "unity-create-project.log"
        command = [
            str(unity_exe),
            "-batchmode",
            "-quit",
            "-createProject",
            str(project_path),
            "-logFile",
            str(log_path),
        ]
        result = subprocess.run(command, check=False, timeout=1800)
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to create Unity project at '{project_path}'. See '{log_path}'."
            )

    @staticmethod
    def _require_windows() -> None:
        if platform.system().lower() != "windows":
            raise RuntimeError("robotframework-unity-editor supports Windows only.")
