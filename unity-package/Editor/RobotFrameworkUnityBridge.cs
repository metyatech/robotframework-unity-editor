#if UNITY_EDITOR
using System;
using System.Collections.Generic;
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
    private const int RequestDispatchTimeoutMs = 5000;
    private static HttpListener _listener;
    private static Thread _listenerThread;
    private static readonly object MainThreadQueueLock = new object();
    private static readonly Queue<Action> MainThreadQueue = new Queue<Action>();
    private static readonly object SelectionStateLock = new object();
    private static long _selectionVersion = 0;
    private static string _selectionHierarchyPath = "";
    private static long _selectionChangedUnixMs = 0;

    [Serializable]
    private class SelectionPayload
    {
        public bool ok;
        public string hierarchy_path;
        public long selection_version;
        public long selection_changed_unix_ms;
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
        EditorApplication.update += PumpMainThreadQueue;
        AssemblyReloadEvents.beforeAssemblyReload += StopBridge;
        EditorApplication.quitting += StopBridge;
        Selection.selectionChanged += OnSelectionChanged;
    }

    private static void StartBridge()
    {
        if (_listener != null)
        {
            return;
        }

        UpdateSelectionState();

        try
        {
            _listener = new HttpListener();
            _listener.Prefixes.Add($"http://127.0.0.1:{Port}/");
            _listener.Start();
            _listenerThread = new Thread(ListenLoop) { IsBackground = true };
            _listenerThread.Start();
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
            // ignore shutdown errors
        }
        finally
        {
            _listener = null;
        }
        var listenerThread = _listenerThread;
        _listenerThread = null;
        if (listenerThread != null && listenerThread.IsAlive)
        {
            try
            {
                listenerThread.Join(500);
            }
            catch
            {
                // ignore join errors
            }
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

            HandleRequest(context);
        }
    }

    private static void PumpMainThreadQueue()
    {
        while (true)
        {
            Action action = null;
            lock (MainThreadQueueLock)
            {
                if (MainThreadQueue.Count == 0)
                {
                    break;
                }
                action = MainThreadQueue.Dequeue();
            }

            try
            {
                action?.Invoke();
            }
            catch (Exception ex)
            {
                Debug.LogWarning(
                    $"[RobotFrameworkUnityBridge] Main-thread action failed: {ex.Message}"
                );
            }
        }
    }

    private static void OnSelectionChanged()
    {
        UpdateSelectionState();
    }

    private static void UpdateSelectionState()
    {
        var hierarchyPath = GetSelectedHierarchyPath();
        lock (SelectionStateLock)
        {
            _selectionVersion += 1;
            _selectionHierarchyPath = hierarchyPath ?? "";
            _selectionChangedUnixMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            Monitor.PulseAll(SelectionStateLock);
        }
    }

    private static bool ExecuteOnMainThread<T>(
        Func<T> function,
        int timeoutMs,
        out T result,
        out string error
    )
    {
        var done = new ManualResetEventSlim(false);
        Exception captured = null;
        T local = default;

        lock (MainThreadQueueLock)
        {
            MainThreadQueue.Enqueue(() =>
            {
                try
                {
                    local = function();
                }
                catch (Exception ex)
                {
                    captured = ex;
                }
                finally
                {
                    done.Set();
                }
            });
        }

        if (!done.Wait(Math.Max(1, timeoutMs)))
        {
            result = default;
            error = $"Main-thread dispatch timed out after {timeoutMs} ms.";
            return false;
        }

        if (captured != null)
        {
            result = default;
            error = captured.Message;
            return false;
        }

        result = local;
        error = "";
        return true;
    }

    private static bool ExecuteOnMainThread(Action action, int timeoutMs, out string error)
    {
        return ExecuteOnMainThread(
            () =>
            {
                action();
                return true;
            },
            timeoutMs,
            out _,
            out error
        );
    }

    private static void HandleRequest(HttpListenerContext context)
    {
        try
        {
            var method = context.Request.HttpMethod.ToUpperInvariant();
            var path = context.Request.Url?.AbsolutePath ?? "/";

            if (method == "GET" && path == "/v1/selection/wait")
            {
                long afterVersion = 0;
                var afterRaw = context.Request.QueryString["after_version"] ?? "";
                long.TryParse(afterRaw, out afterVersion);

                var timeoutMs = 350;
                var timeoutRaw = context.Request.QueryString["timeout_ms"] ?? "";
                if (int.TryParse(timeoutRaw, out int parsedTimeoutMs))
                {
                    timeoutMs = parsedTimeoutMs;
                }
                timeoutMs = Math.Max(0, Math.Min(15000, timeoutMs));

                var deadline = DateTime.UtcNow.AddMilliseconds(timeoutMs);
                SelectionPayload payload;
                lock (SelectionStateLock)
                {
                    while (_selectionVersion <= afterVersion)
                    {
                        var remainingMs = (int)Math.Ceiling(
                            (deadline - DateTime.UtcNow).TotalMilliseconds
                        );
                        if (remainingMs <= 0)
                        {
                            break;
                        }
                        Monitor.Wait(SelectionStateLock, remainingMs);
                    }
                    payload = new SelectionPayload
                    {
                        ok = true,
                        hierarchy_path = _selectionHierarchyPath ?? "",
                        selection_version = _selectionVersion,
                        selection_changed_unix_ms = _selectionChangedUnixMs,
                        error = ""
                    };
                }

                WriteJson(context.Response, 200, payload);
                return;
            }

            if (method == "GET" && path == "/v1/selection")
            {
                SelectionPayload payload;
                lock (SelectionStateLock)
                {
                    payload = new SelectionPayload
                    {
                        ok = true,
                        hierarchy_path = _selectionHierarchyPath ?? "",
                        selection_version = _selectionVersion,
                        selection_changed_unix_ms = _selectionChangedUnixMs,
                        error = ""
                    };
                }
                WriteJson(context.Response, 200, payload);
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

                var selected = false;
                if (
                    !ExecuteOnMainThread(
                        () =>
                        {
                            var target = FindByHierarchyPath(normalized);
                            if (target == null)
                            {
                                selected = false;
                                return;
                            }
                            Selection.activeGameObject = target;
                            EditorGUIUtility.PingObject(target);
                            selected = true;
                        },
                        RequestDispatchTimeoutMs,
                        out string dispatchError
                    )
                )
                {
                    WriteJson(
                        context.Response,
                        503,
                        new SelectionPayload
                        {
                            ok = false,
                            hierarchy_path = normalized,
                            error = dispatchError
                        }
                    );
                    return;
                }

                if (!selected)
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

                WriteJson(
                    context.Response,
                    200,
                    new SelectionPayload
                    {
                        ok = true,
                        hierarchy_path = normalized,
                        selection_version = _selectionVersion,
                        selection_changed_unix_ms = _selectionChangedUnixMs,
                        error = ""
                    }
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
                    selection_version = _selectionVersion,
                    selection_changed_unix_ms = _selectionChangedUnixMs,
                    error = "Endpoint not found."
                }
            );
        }
        catch (Exception ex)
        {
            WriteJson(
                context.Response,
                500,
                new SelectionPayload
                {
                    ok = false,
                    hierarchy_path = "",
                    selection_version = _selectionVersion,
                    selection_changed_unix_ms = _selectionChangedUnixMs,
                    error = ex.Message
                }
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
        var allowAnyRoot = string.Equals(segments[0], "*", StringComparison.Ordinal);
        if (allowAnyRoot && segments.Length < 2)
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
                if (
                    !allowAnyRoot
                    && !string.Equals(root.name, segments[0], StringComparison.Ordinal)
                )
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
        try
        {
            response.StatusCode = statusCode;
            response.ContentType = "application/json; charset=utf-8";
            var json = JsonUtility.ToJson(payload);
            var bytes = Encoding.UTF8.GetBytes(json);
            response.ContentLength64 = bytes.Length;
            using var output = response.OutputStream;
            output.Write(bytes, 0, bytes.Length);
        }
        catch
        {
            // client may disconnect before response flush
        }
    }
}
#endif
