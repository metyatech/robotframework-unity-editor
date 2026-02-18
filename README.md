# robotframework-unity-editor

Robot Framework library for automating Unity Editor on Windows and emitting metadata for guidebook artifact generation.

## Overview

This package provides reusable Robot keywords for Unity Editor GUI automation:

- Unity startup, attach, focus, maximize, and shutdown
- Relative click/drag operations for stable scenario definitions
- Keyboard input and shortcut execution
- Top menu access and UI element lookup (title/automation id/class/control type)
- Unity hierarchy selection bridge (`hierarchy_path`) for custom-drawn panes
- Unity bridge UPM dependency management (`Packages/manifest.json`)
- Unity window screenshots
- `DOCMETA` emission for downstream annotation pipelines (`click`, `click_pulse`, `drag_arrow`, `label`)

## Supported Environment

- OS: Windows 10/11
- Python: 3.11+
- Unity Editor: any recent Hub-installed version with `Unity.exe`
- Robot Framework: 7.x

## Install

```bash
python -m pip install robotframework-unity-editor
```

For development:

```bash
python -m pip install -e ".[dev]"
```

## Usage

Import the library in your `.robot` suite:

```robot
*** Settings ***
Library    robotframework_unity_editor.UnityEditorLibrary

*** Test Cases ***
Unity Basic Scenario
    Set Unity Output Directory    artifacts/unity
    Attach To Running Unity Editor    window_hint=Unity
    Focus Unity Window
    ${annotation}=    Click Unity Relative    0.07    0.05
    Emit DOCMETA    {"annotation": ${annotation}}
    ${drag}=    Drag Unity Relative    0.22    0.43    0.68    0.45
    Emit DOCMETA    {"annotation": ${drag}}
    Stop Unity Editor
```

Hierarchy path example (requires Unity bridge package in the target project):

```robot
*** Test Cases ***
Select Tail From Hierarchy
    Attach To Running Unity Editor    window_hint=Unity
    ${annotation}=    Select Unity Hierarchy Object    hierarchy_path=AvatarRoot/Hair/Tail
    Emit DOCMETA    {"annotation": ${annotation}}
```

Annotation payloads returned by common action keywords:

- `Click Unity Relative` / `Click Unity Element(button=left)`:
  `{"type":"click","box":{...}}`
- `Double Click Unity Relative` / `Right Click Unity Relative` / `Click Unity Element(button=right)`:
  `{"type":"click_pulse","box":{...}}`
- `Drag Unity Relative` / `Drag Unity Element To Element`:
  `{"type":"drag_arrow","from":{...},"to":{...}}`
- `Select Unity Hierarchy Object`:
  `{"type":"label","text":"AvatarRoot/Hair/Tail"}`

Ensure Unity bridge UPM package in a Unity project:

```robot
*** Test Cases ***
Ensure Bridge
    Ensure Unity Bridge UPM Package    D:/projects/my-unity-project
```

UPM dependency used by default:

```text
com.metyatech.unity-automation-bridge
  -> https://github.com/metyatech/robotframework-unity-editor.git?path=/unity-package#main
```

`Ensure Unity Bridge UPM Package` also removes legacy bridge script
`Assets/Editor/RobotFrameworkUnityBridge.cs` (and `.meta`) when present.

## Key Keywords

- `Set Unity Output Directory`
- `Start Unity Editor`
- `Attach To Running Unity Editor`
- `Connect Unity Editor`
- `Ensure Unity Window Stable`
- `Get Unity Window Rect`
- `Click Unity Relative`
- `Double Click Unity Relative`
- `Right Click Unity Relative`
- `Drag Unity Relative`
- `Press Unity Keys`
- `Send Unity Shortcut`
- `Open Unity Top Menu`
- `Wait For Unity Element`
- `Get Unity Element Rect`
- `Click Unity Element`
- `Drag Unity Element To Element`
- `Get Unity Selected Hierarchy Path`
- `Select Unity Hierarchy Object`
- `Ensure Unity Bridge UPM Package`
- `Install Unity Editor Bridge Script`
- `Capture Unity Screenshot`
- `Emit DOCMETA`
- `Emit Click DOCMETA`
- `Emit Drag DOCMETA`
- `Stop Unity Editor`

## Development

```bash
python -m pip install -e ".[dev]"
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

## Required Environment Variables

- `UNITY_EDITOR_EXE` (optional): absolute path to `Unity.exe` when auto-discovery is not sufficient.

## Release

1. Update `version` in `pyproject.toml`.
2. Update `CHANGELOG.md`.
3. Tag and publish from CI or local build pipeline.

## Links

- Security policy: `SECURITY.md`
- Contributing guide: `CONTRIBUTING.md`
- Code of Conduct: `CODE_OF_CONDUCT.md`
- License: `LICENSE`
- Changelog: `CHANGELOG.md`
