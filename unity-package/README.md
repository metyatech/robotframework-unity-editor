# Unity Automation Bridge

UPM package that provides a Unity Editor HTTP bridge used by automation tools.

## Install (Git URL)

Add this dependency to `Packages/manifest.json`:

```json
{
  "dependencies": {
    "com.metyatech.unity-automation-bridge": "https://github.com/metyatech/robotframework-unity-editor.git?path=/unity-package#main"
  }
}
```

## Endpoints

- `GET /v1/selection`
- `POST /v1/select`

Both are served on `http://127.0.0.1:39067/` from inside Unity Editor.
