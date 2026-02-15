#if UNITY_EDITOR
using System;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using UnityEditor;
using UnityEngine;
using UnityEngine.SceneManagement;

[InitializeOnLoad]
public static class RobotFrameworkUnityBridge
{
    private const int Port = 39067;
    private static HttpListener _listener;
    private static Thread _thread;

    [Serializable]
    private class SelectionPayload
    {
        public bool ok;
        public string hierarchy_path;
        public string error;
    }

    [Serializable]
    private class SelectRequest
    {
        public string hierarchy_path;
    }

    static RobotFrameworkUnityBridge()
    {
        EditorApplication.delayCall += StartBridge;
        AssemblyReloadEvents.beforeAssemblyReload += StopBridge;
        EditorApplication.quitting += StopBridge;
    }

    private static void StartBridge()
    {
        if (_listener != null)
        {
            return;
        }

        try
        {
            _listener = new HttpListener();
            _listener.Prefixes.Add($"http://127.0.0.1:{Port}/");
            _listener.Start();
            _thread = new Thread(ListenLoop) { IsBackground = true };
            _thread.Start();
            Debug.Log($"[RobotFrameworkUnityBridge] Listening on 127.0.0.1:{Port}");
        }
        catch (Exception ex)
        {
            Debug.LogWarning($"[RobotFrameworkUnityBridge] Failed to start: {ex.Message}");
        }
    }

    private static void StopBridge()
    {
        try
        {
            _listener?.Stop();
            _listener?.Close();
        }
        catch
        {
        }
        finally
        {
            _listener = null;
        }
    }

    private static void ListenLoop()
    {
        while (_listener != null && _listener.IsListening)
        {
            HttpListenerContext context = null;
            try
            {
                context = _listener.GetContext();
            }
            catch
            {
                break;
            }
            if (context == null)
            {
                continue;
            }

            var capturedContext = context;
            EditorApplication.delayCall += () => HandleRequest(capturedContext);
        }
    }

    private static void HandleRequest(HttpListenerContext context)
    {
        try
        {
            var method = context.Request.HttpMethod.ToUpperInvariant();
            var path = context.Request.Url.AbsolutePath ?? "/";

            if (method == "GET" && path == "/v1/selection")
            {
                var hierarchyPath = GetSelectedHierarchyPath();
                WriteJson(
                    context.Response,
                    200,
                    new SelectionPayload { ok = true, hierarchy_path = hierarchyPath, error = "" }
                );
                return;
            }

            if (method == "POST" && path == "/v1/select")
            {
                using var reader = new StreamReader(context.Request.InputStream, Encoding.UTF8);
                var body = reader.ReadToEnd();
                var request =
                    JsonUtility.FromJson<SelectRequest>(body ?? "")
                    ?? new SelectRequest();
                var normalized = NormalizePath(request.hierarchy_path);
                if (string.IsNullOrEmpty(normalized))
                {
                    WriteJson(
                        context.Response,
                        400,
                        new SelectionPayload
                        {
                            ok = false,
                            hierarchy_path = "",
                            error = "hierarchy_path is required."
                        }
                    );
                    return;
                }

                var target = FindByHierarchyPath(normalized);
                if (target == null)
                {
                    WriteJson(
                        context.Response,
                        404,
                        new SelectionPayload
                        {
                            ok = false,
                            hierarchy_path = normalized,
                            error = $"GameObject not found: {normalized}"
                        }
                    );
                    return;
                }

                Selection.activeGameObject = target;
                EditorGUIUtility.PingObject(target);
                WriteJson(
                    context.Response,
                    200,
                    new SelectionPayload { ok = true, hierarchy_path = normalized, error = "" }
                );
                return;
            }

            WriteJson(
                context.Response,
                404,
                new SelectionPayload
                {
                    ok = false,
                    hierarchy_path = "",
                    error = "Endpoint not found."
                }
            );
        }
        catch (Exception ex)
        {
            WriteJson(
                context.Response,
                500,
                new SelectionPayload { ok = false, hierarchy_path = "", error = ex.Message }
            );
        }
    }

    private static string GetSelectedHierarchyPath()
    {
        var go = Selection.activeGameObject;
        if (go == null)
        {
            return "";
        }
        return BuildHierarchyPath(go.transform);
    }

    private static string BuildHierarchyPath(Transform transform)
    {
        if (transform == null)
        {
            return "";
        }
        var segments = transform.name;
        var current = transform.parent;
        while (current != null)
        {
            segments = current.name + "/" + segments;
            current = current.parent;
        }
        return segments;
    }

    private static GameObject FindByHierarchyPath(string hierarchyPath)
    {
        var segments = hierarchyPath.Split(new[] { '/' }, StringSplitOptions.RemoveEmptyEntries);
        if (segments.Length == 0)
        {
            return null;
        }

        for (var sceneIndex = 0; sceneIndex < SceneManager.sceneCount; sceneIndex++)
        {
            var scene = SceneManager.GetSceneAt(sceneIndex);
            if (!scene.IsValid() || !scene.isLoaded)
            {
                continue;
            }

            foreach (var root in scene.GetRootGameObjects())
            {
                if (!string.Equals(root.name, segments[0], StringComparison.Ordinal))
                {
                    continue;
                }

                var current = root.transform;
                var found = true;
                for (var i = 1; i < segments.Length; i++)
                {
                    current = current.Find(segments[i]);
                    if (current == null)
                    {
                        found = false;
                        break;
                    }
                }

                if (found && current != null)
                {
                    return current.gameObject;
                }
            }
        }

        return null;
    }

    private static string NormalizePath(string raw)
    {
        if (string.IsNullOrEmpty(raw))
        {
            return "";
        }
        var normalized = raw.Replace('\\', '/').Trim();
        while (normalized.Contains("//"))
        {
            normalized = normalized.Replace("//", "/");
        }
        return normalized.Trim('/');
    }

    private static void WriteJson(
        HttpListenerResponse response,
        int statusCode,
        SelectionPayload payload
    )
    {
        response.StatusCode = statusCode;
        response.ContentType = "application/json; charset=utf-8";
        var json = JsonUtility.ToJson(payload);
        var bytes = Encoding.UTF8.GetBytes(json);
        response.ContentLength64 = bytes.Length;
        response.OutputStream.Write(bytes, 0, bytes.Length);
        response.OutputStream.Close();
    }
}
#endif
