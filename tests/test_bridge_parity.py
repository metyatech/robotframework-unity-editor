from __future__ import annotations

from pathlib import Path


def _read_upm_bridge_text() -> str:
    return Path("unity-package/Editor/RobotFrameworkUnityBridge.cs").read_text(encoding="utf-8")


def test_upm_bridge_supports_any_root_hierarchy_paths() -> None:
    # The Studio recorder can emit hierarchy fallback paths like "*/Hair/Tail".
    # The UPM bridge implementation must support resolving these paths.
    text = _read_upm_bridge_text()
    assert "allowAnyRoot" in text
    assert "segments[0]" in text
    assert '"*"' in text


def test_upm_bridge_exposes_selection_version_state() -> None:
    # Selection version + timestamp enable non-blocking, correct ordering during recording.
    text = _read_upm_bridge_text()
    assert "selection_version" in text
    assert "selection_changed_unix_ms" in text


def test_upm_bridge_supports_wait_for_selection_change_endpoint() -> None:
    # Studio uses /v1/selection/wait to avoid recording stale hierarchy selections.
    text = _read_upm_bridge_text()
    assert "/v1/selection/wait" in text
