# robotframework-unity-editor

Robot Framework library for automating Unity Editor on Windows and emitting metadata for guidebook artifact generation.

## Overview

This package provides reusable Robot keywords for Unity Editor GUI automation:

- Unity startup, attach, focus, maximize, and shutdown
- Relative click/drag operations for stable scenario definitions
- Keyboard input and shortcut execution
- Top menu access and UI element lookup (title/automation id/class/control type)
- Unity window screenshots
- `DOCMETA` emission for downstream annotation pipelines (click/drag)

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
- License: `LICENSE`
- Changelog: `CHANGELOG.md`
