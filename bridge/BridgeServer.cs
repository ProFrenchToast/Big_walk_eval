using System;
using System.Collections.Concurrent;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;

namespace BigWalk.EvalBridge;

internal sealed class Request
{
    public long Id;
    public string Cmd;
    public JsonObject Args;

    public readonly TaskCompletionSource<JsonNode> Done =
        new(TaskCreationOptions.RunContinuationsAsynchronously);
}

/// <summary>
/// TCP listener on a background thread. Unity APIs work only on the main
/// thread, so each request goes into <see cref="Queue"/>; BridgeBehaviour
/// runs it in Update and completes <see cref="Request.Done"/>. This thread
/// never touches Unity or Il2Cpp objects.
/// </summary>
internal sealed class BridgeServer
{
    internal static readonly ConcurrentQueue<Request> Queue = new();

    private static readonly TimeSpan RequestTimeout = TimeSpan.FromSeconds(120);
    private static readonly UTF8Encoding Utf8 = new(false);

    private readonly int _port;
    private TcpListener _listener;
    private Thread _acceptThread;
    private volatile bool _running;

    public BridgeServer(int port)
    {
        _port = port;
    }

    public void Start()
    {
        _listener = new TcpListener(IPAddress.Loopback, _port);
        _listener.Start();
        _running = true;
        _acceptThread = new Thread(AcceptLoop) { IsBackground = true, Name = "EvalBridge.Accept" };
        _acceptThread.Start();
    }

    public void Stop()
    {
        _running = false;
        try
        {
            _listener?.Stop();
        }
        catch (SocketException)
        {
        }
    }

    private void AcceptLoop()
    {
        while (_running)
        {
            TcpClient client;
            try
            {
                client = _listener.AcceptTcpClient();
            }
            catch (SocketException)
            {
                if (!_running) return;
                continue;
            }
            catch (ObjectDisposedException)
            {
                return;
            }

            var thread = new Thread(() => Serve(client)) { IsBackground = true, Name = "EvalBridge.Client" };
            thread.Start();
        }
    }

    private static void Serve(TcpClient client)
    {
        Plugin.Trace.LogInfo("Game server connected.");
        try
        {
            using (client)
            using (var stream = client.GetStream())
            using (var reader = new StreamReader(stream, Utf8))
            using (var writer = new StreamWriter(stream, Utf8) { AutoFlush = true, NewLine = "\n" })
            {
                string line;
                while ((line = reader.ReadLine()) != null)
                {
                    if (line.Length == 0) continue;
                    writer.WriteLine(Handle(line));
                }
            }
        }
        catch (IOException)
        {
        }

        Plugin.Trace.LogInfo("Game server disconnected.");
    }

    private static string Handle(string line)
    {
        long id = 0;
        string cmd = "";
        try
        {
            var message = JsonNode.Parse(line).AsObject();
            id = message["id"]?.GetValue<long>() ?? 0;
            cmd = message["cmd"]?.GetValue<string>() ?? "";
            var request = new Request
            {
                Id = id,
                Cmd = cmd,
                Args = (message["args"] as JsonObject)?.DeepClone().AsObject() ?? new JsonObject(),
            };
            Queue.Enqueue(request);
            if (!request.Done.Task.Wait(RequestTimeout))
            {
                return Error(id, $"{cmd}: timed out waiting for the main thread");
            }

            return new JsonObject
            {
                ["id"] = id,
                ["ok"] = true,
                ["result"] = request.Done.Task.Result,
            }.ToJsonString();
        }
        catch (AggregateException e)
        {
            return Error(id, $"{cmd}: {e.InnerException?.Message ?? e.Message}");
        }
        catch (Exception e)
        {
            return Error(id, $"{cmd}: {e.Message}");
        }
    }

    private static string Error(long id, string message)
    {
        return new JsonObject { ["id"] = id, ["ok"] = false, ["error"] = message }.ToJsonString();
    }
}
