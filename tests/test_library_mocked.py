import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from robotframework_unity_editor.library import UnityEditorLibrary


@pytest.fixture
def library_instance(tmp_path: Path) -> UnityEditorLibrary:
    return UnityEditorLibrary(output_dir=str(tmp_path))


def test_set_unity_output_directory(library_instance: UnityEditorLibrary, tmp_path: Path) -> None:
    new_dir = tmp_path / "new_out"
    library_instance.set_unity_output_directory(str(new_dir))
    assert library_instance.get_unity_output_directory() == str(new_dir.resolve())
    assert new_dir.exists()


def test_set_unity_bridge_endpoint(library_instance: UnityEditorLibrary) -> None:
    library_instance.set_unity_bridge_endpoint("192.168.1.1", 12345)
    assert library_instance.get_unity_bridge_endpoint() == "http://192.168.1.1:12345"


@patch("robotframework_unity_editor.library.Application")
@patch("robotframework_unity_editor.library.win32gui")
@patch("robotframework_unity_editor.library.win32process")
def test_attach_to_running_unity_editor(
    mock_win32process: MagicMock,
    mock_win32gui: MagicMock,
    mock_app_class: MagicMock,
    library_instance: UnityEditorLibrary,
) -> None:
    mock_win32gui.GetForegroundWindow.return_value = 123
    mock_win32gui.IsWindowVisible.return_value = True
    mock_win32gui.GetWindowText.return_value = "My Project - Unity 2022.3.0f1"

    # EnumWindows mock
    def mock_enum_windows(callback, lparam):
        callback(123, lparam)

    mock_win32gui.EnumWindows.side_effect = mock_enum_windows

    mock_win32process.GetWindowThreadProcessId.return_value = (None, 4567)

    mock_app = MagicMock()
    mock_app_class.return_value = mock_app
    mock_app.connect.return_value = mock_app
    mock_window = MagicMock()
    mock_app.window.return_value = mock_window
    mock_window.exists.return_value = True
    mock_window.is_visible.return_value = True

    pid = library_instance.attach_to_running_unity_editor(window_hint="Unity", timeout_seconds=1)

    assert pid == 4567
    assert library_instance._unity_pid == 4567
    assert library_instance._window == mock_window


@patch("robotframework_unity_editor.library.urllib.request.urlopen")
def test_request_unity_bridge_success(
    mock_urlopen: MagicMock,
    library_instance: UnityEditorLibrary,
) -> None:
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(
        {"ok": True, "hierarchy_path": "Root/Child"}
    ).encode("utf-8")
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    result = library_instance._request_unity_bridge("GET", "/v1/selection")

    assert result["ok"] is True
    assert result["hierarchy_path"] == "Root/Child"


def test_find_element_raises_when_no_criteria(library_instance: UnityEditorLibrary) -> None:
    library_instance._window = MagicMock()
    with pytest.raises(ValueError, match="At least one selector is required"):
        library_instance._find_element()


def test_find_element_success(library_instance: UnityEditorLibrary) -> None:
    mock_window = MagicMock()
    library_instance._window = mock_window
    mock_element = MagicMock()
    mock_child = MagicMock()
    mock_child.wrapper_object.return_value = mock_element
    mock_window.child_window.return_value = mock_child

    element = library_instance._find_element(title="Hierarchy")

    assert element == mock_element
    mock_window.child_window.assert_called_once_with(title="Hierarchy")


def test_find_element_timeout(library_instance: UnityEditorLibrary) -> None:
    mock_window = MagicMock()
    library_instance._window = mock_window
    mock_window.child_window.side_effect = Exception("Not found")

    with pytest.raises(RuntimeError, match="Unity element was not found"):
        library_instance._find_element(title="Hierarchy", timeout_seconds=0.1)
