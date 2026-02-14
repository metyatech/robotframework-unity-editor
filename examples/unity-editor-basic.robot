*** Settings ***
Library    robotframework_unity_editor.UnityEditorLibrary

*** Test Cases ***
Unity Editor Basic Flow
    Set Unity Output Directory    artifacts/unity
    Start Unity Editor
    Maximize Unity Window
    Focus Unity Window
    ${click_annotation}=    Click Unity Relative    0.07    0.05
    Emit DOCMETA    {"annotation": ${click_annotation}}
    ${drag_annotation}=    Drag Unity Relative    0.22    0.43    0.68    0.45
    Emit DOCMETA    {"annotation": ${drag_annotation}}
    Capture Unity Screenshot
    Stop Unity Editor
