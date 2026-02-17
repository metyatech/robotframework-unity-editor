import json
from pathlib import Path

import pytest

from robotframework_unity_editor.bridge_script import UNITY_EDITOR_BRIDGE_SCRIPT
from robotframework_unity_editor.library import (
    DEFAULT_UNITY_BRIDGE_PACKAGE_NAME,
    DEFAULT_UNITY_BRIDGE_PACKAGE_URL,
    UnityEditorLibrary,
    build_click_annotation,
    build_click_annotation_with_type,
    build_drag_annotation,
    build_hierarchy_select_annotation,
    clamp_ratio,
    ensure_upm_dependency_in_manifest,
    find_unity_executable,
    has_unity_bridge_package_script_meta,
    normalize_hierarchy_path,
    pick_unity_window_handle,
    shortcut_to_send_keys,
    title_matches_window_hint,
)


def test_bridge_script_uses_main_thread_queue_dispatch() -> None:
    assert "EditorApplication.update += PumpMainThreadQueue;" in UNITY_EDITOR_BRIDGE_SCRIPT
    assert "ExecuteOnMainThread(" in UNITY_EDITOR_BRIDGE_SCRIPT


def test_bridge_script_does_not_dispatch_requests_via_delay_call_from_listener_thread() -> None:
    assert (
        "EditorApplication.delayCall += () => HandleRequest(capturedContext);"
        not in UNITY_EDITOR_BRIDGE_SCRIPT
    )


def test_bridge_script_includes_selection_version_in_payload() -> None:
    assert "public long selection_version;" in UNITY_EDITOR_BRIDGE_SCRIPT


def test_bridge_script_tracks_selection_changes_with_versioning() -> None:
    assert "Selection.selectionChanged +=" in UNITY_EDITOR_BRIDGE_SCRIPT


def test_bridge_script_supports_selection_wait_endpoint() -> None:
    assert 'path == "/v1/selection/wait"' in UNITY_EDITOR_BRIDGE_SCRIPT
    assert "Monitor.Wait" in UNITY_EDITOR_BRIDGE_SCRIPT


def test_bridge_script_includes_selection_changed_timestamp_in_payload() -> None:
    assert "public long selection_changed_unix_ms;" in UNITY_EDITOR_BRIDGE_SCRIPT
    assert "DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()" in UNITY_EDITOR_BRIDGE_SCRIPT


def test_bridge_script_supports_wildcard_root_hierarchy_paths() -> None:
    assert (
        'var allowAnyRoot = string.Equals(segments[0], "*", StringComparison.Ordinal);'
        in UNITY_EDITOR_BRIDGE_SCRIPT
    )
    assert "if (allowAnyRoot && segments.Length < 2)" in UNITY_EDITOR_BRIDGE_SCRIPT
    assert "!allowAnyRoot" in UNITY_EDITOR_BRIDGE_SCRIPT
    assert "string.Equals(root.name, segments[0], StringComparison.Ordinal)" in (
        UNITY_EDITOR_BRIDGE_SCRIPT
    )


def test_clamp_ratio_limits_values() -> None:
    assert clamp_ratio(-0.5) == 0.0
    assert clamp_ratio(0.4) == 0.4
    assert clamp_ratio(1.4) == 1.0


def test_build_click_annotation() -> None:
    annotation = build_click_annotation(x=100, y=70, width=40, height=20)
    assert annotation == {
        "type": "click",
        "box": {
            "x": 80,
            "y": 60,
            "width": 40,
            "height": 20,
        },
    }


def test_build_click_pulse_annotation() -> None:
    annotation = build_click_annotation_with_type(
        x=100,
        y=70,
        width=40,
        height=20,
        annotation_type="click_pulse",
    )
    assert annotation == {
        "type": "click_pulse",
        "box": {
            "x": 80,
            "y": 60,
            "width": 40,
            "height": 20,
        },
    }


def test_build_drag_annotation() -> None:
    annotation = build_drag_annotation(from_x=10, from_y=20, to_x=80, to_y=100)
    assert annotation == {
        "type": "drag_arrow",
        "from": {"x": 10, "y": 20},
        "to": {"x": 80, "y": 100},
    }


def test_normalize_hierarchy_path() -> None:
    assert normalize_hierarchy_path("Root/Child") == "Root/Child"
    assert normalize_hierarchy_path(" /Root//Child/ ") == "Root/Child"


def test_build_hierarchy_select_annotation() -> None:
    assert build_hierarchy_select_annotation("Root/Child") == {
        "type": "label",
        "text": "Root/Child",
    }


def test_ensure_upm_dependency_in_manifest_adds_dependency() -> None:
    manifest = {"dependencies": {"com.unity.textmeshpro": "3.0.6"}}
    changed = ensure_upm_dependency_in_manifest(
        manifest,
        package_name=DEFAULT_UNITY_BRIDGE_PACKAGE_NAME,
        package_url=DEFAULT_UNITY_BRIDGE_PACKAGE_URL,
    )
    assert changed is True
    assert manifest["dependencies"][DEFAULT_UNITY_BRIDGE_PACKAGE_NAME] == (
        DEFAULT_UNITY_BRIDGE_PACKAGE_URL
    )


def test_ensure_upm_dependency_in_manifest_is_idempotent() -> None:
    manifest = {
        "dependencies": {
            DEFAULT_UNITY_BRIDGE_PACKAGE_NAME: DEFAULT_UNITY_BRIDGE_PACKAGE_URL,
        }
    }
    changed = ensure_upm_dependency_in_manifest(
        manifest,
        package_name=DEFAULT_UNITY_BRIDGE_PACKAGE_NAME,
        package_url=DEFAULT_UNITY_BRIDGE_PACKAGE_URL,
    )
    assert changed is False


def test_ensure_upm_dependency_in_manifest_keeps_existing_source() -> None:
    existing_url = "file:../local-packages/unity-automation-bridge"
    manifest = {
        "dependencies": {
            DEFAULT_UNITY_BRIDGE_PACKAGE_NAME: existing_url,
        }
    }
    changed = ensure_upm_dependency_in_manifest(
        manifest,
        package_name=DEFAULT_UNITY_BRIDGE_PACKAGE_NAME,
        package_url=DEFAULT_UNITY_BRIDGE_PACKAGE_URL,
    )
    assert changed is False
    assert manifest["dependencies"][DEFAULT_UNITY_BRIDGE_PACKAGE_NAME] == existing_url


def test_ensure_unity_bridge_upm_package_keyword_updates_manifest(tmp_path: Path) -> None:
    project_path = tmp_path / "sample-project"
    packages_dir = project_path / "Packages"
    packages_dir.mkdir(parents=True)
    manifest_path = packages_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps({"dependencies": {"com.unity.textmeshpro": "3.0.6"}}, indent=2),
        encoding="utf-8",
    )

    library = UnityEditorLibrary(output_dir=str(tmp_path))
    changed = library.ensure_unity_bridge_upm_package(str(project_path))
    unchanged = library.ensure_unity_bridge_upm_package(str(project_path))

    assert changed is True
    assert unchanged is False
    parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert parsed["dependencies"][DEFAULT_UNITY_BRIDGE_PACKAGE_NAME] == (
        DEFAULT_UNITY_BRIDGE_PACKAGE_URL
    )


def test_has_unity_bridge_package_script_meta_detects_cache_meta(tmp_path: Path) -> None:
    project_path = tmp_path / "sample-project"
    meta_path = (
        project_path
        / "Library"
        / "PackageCache"
        / "com.metyatech.unity-automation-bridge@abc123"
        / "Editor"
        / "RobotFrameworkUnityBridge.cs.meta"
    )
    meta_path.parent.mkdir(parents=True)
    meta_path.write_text("fileFormatVersion: 2", encoding="utf-8")

    assert has_unity_bridge_package_script_meta(project_path) is True


def test_ensure_unity_bridge_upm_package_keyword_removes_legacy_script_with_package_meta(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "sample-project"
    packages_dir = project_path / "Packages"
    packages_dir.mkdir(parents=True)
    manifest_path = packages_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {"dependencies": {DEFAULT_UNITY_BRIDGE_PACKAGE_NAME: DEFAULT_UNITY_BRIDGE_PACKAGE_URL}},
            indent=2,
        ),
        encoding="utf-8",
    )
    legacy_script = project_path / "Assets" / "Editor" / "RobotFrameworkUnityBridge.cs"
    legacy_meta = project_path / "Assets" / "Editor" / "RobotFrameworkUnityBridge.cs.meta"
    legacy_script.parent.mkdir(parents=True)
    legacy_script.write_text("// legacy", encoding="utf-8")
    legacy_meta.write_text("fileFormatVersion: 2", encoding="utf-8")
    package_meta_path = (
        project_path
        / "Library"
        / "PackageCache"
        / "com.metyatech.unity-automation-bridge@abc123"
        / "Editor"
        / "RobotFrameworkUnityBridge.cs.meta"
    )
    package_meta_path.parent.mkdir(parents=True)
    package_meta_path.write_text("fileFormatVersion: 2", encoding="utf-8")

    library = UnityEditorLibrary(output_dir=str(tmp_path))
    changed = library.ensure_unity_bridge_upm_package(str(project_path))

    assert changed is True
    assert not legacy_script.exists()
    assert not legacy_meta.exists()


def test_ensure_unity_bridge_upm_package_keyword_keeps_legacy_script_without_package_meta(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "sample-project"
    packages_dir = project_path / "Packages"
    packages_dir.mkdir(parents=True)
    manifest_path = packages_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {"dependencies": {DEFAULT_UNITY_BRIDGE_PACKAGE_NAME: DEFAULT_UNITY_BRIDGE_PACKAGE_URL}},
            indent=2,
        ),
        encoding="utf-8",
    )
    legacy_script = project_path / "Assets" / "Editor" / "RobotFrameworkUnityBridge.cs"
    legacy_meta = project_path / "Assets" / "Editor" / "RobotFrameworkUnityBridge.cs.meta"
    legacy_script.parent.mkdir(parents=True)
    legacy_script.write_text("// legacy", encoding="utf-8")
    legacy_meta.write_text("fileFormatVersion: 2", encoding="utf-8")

    library = UnityEditorLibrary(output_dir=str(tmp_path))
    changed = library.ensure_unity_bridge_upm_package(str(project_path))

    assert changed is False
    assert legacy_script.exists()
    assert legacy_meta.exists()


@pytest.mark.parametrize(
    ("shortcut", "expected"),
    [
        ("CTRL+S", "^s"),
        ("CTRL+SHIFT+P", "^+p"),
        ("ALT+F4", "%{F4}"),
        ("CTRL+ALT+DELETE", "^%{DELETE}"),
    ],
)
def test_shortcut_to_send_keys(shortcut: str, expected: str) -> None:
    assert shortcut_to_send_keys(shortcut) == expected


def test_find_unity_executable_prefers_explicit_path(tmp_path: Path) -> None:
    unity_exe = tmp_path / "Unity.exe"
    unity_exe.write_text("stub", encoding="utf-8")
    resolved = find_unity_executable(explicit_path=str(unity_exe))
    assert resolved == unity_exe.resolve()


def test_find_unity_executable_uses_env_value(tmp_path: Path) -> None:
    unity_exe = tmp_path / "UnityFromEnv.exe"
    unity_exe.write_text("stub", encoding="utf-8")
    resolved = find_unity_executable(env_path=str(unity_exe))
    assert resolved == unity_exe.resolve()


def test_find_unity_executable_uses_candidates(tmp_path: Path) -> None:
    missing = tmp_path / "missing.exe"
    found = tmp_path / "UnityCandidate.exe"
    found.write_text("stub", encoding="utf-8")
    resolved = find_unity_executable(candidate_paths=[missing, found])
    assert resolved == found.resolve()


def test_find_unity_executable_raises_when_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        find_unity_executable(candidate_paths=[tmp_path / "missing.exe"])


def test_title_matches_window_hint() -> None:
    assert title_matches_window_hint("MyProject - Unity 2022.3", "Unity")
    assert title_matches_window_hint("Avatar Tooling - Unity", "avatar")
    assert not title_matches_window_hint("Visual Studio Code", "Unity")


def test_pick_unity_window_handle_prefers_foreground() -> None:
    candidates = [
        (10, "Project A - Unity"),
        (20, "Project B - Unity"),
    ]
    selected = pick_unity_window_handle(candidates, "Unity", foreground_handle=20)
    assert selected == 20


def test_pick_unity_window_handle_uses_first_match() -> None:
    candidates = [
        (10, "Project A - Unity"),
        (20, "Project B - Unity"),
    ]
    selected = pick_unity_window_handle(candidates, "Project A")
    assert selected == 10


def test_pick_unity_window_handle_returns_none_when_not_found() -> None:
    candidates = [
        (10, "Visual Studio Code"),
        (20, "Notepad"),
    ]
    selected = pick_unity_window_handle(candidates, "Unity")
    assert selected is None
