from pathlib import Path

import pytest

from robotframework_unity_editor.library import (
    build_click_annotation,
    build_drag_annotation,
    build_hierarchy_select_annotation,
    clamp_ratio,
    find_unity_executable,
    normalize_hierarchy_path,
    pick_unity_window_handle,
    shortcut_to_send_keys,
    title_matches_window_hint,
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


def test_build_drag_annotation() -> None:
    annotation = build_drag_annotation(from_x=10, from_y=20, to_x=80, to_y=100)
    assert annotation == {
        "type": "dragDrop",
        "from": {"x": 10, "y": 20},
        "to": {"x": 80, "y": 100},
    }


def test_normalize_hierarchy_path() -> None:
    assert normalize_hierarchy_path("Root/Child") == "Root/Child"
    assert normalize_hierarchy_path(" /Root//Child/ ") == "Root/Child"


def test_build_hierarchy_select_annotation() -> None:
    assert build_hierarchy_select_annotation("Root/Child") == {
        "type": "hierarchySelect",
        "hierarchyPath": "Root/Child",
    }


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
