import asyncio
import base64
import json
import os
import threading
import uuid

try:
    import websockets
    import websockets.server
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False
    print("[BRIDGE] websockets not installed. Run: pip install websockets")

PORT = int(os.environ.get("DAVI_BRIDGE_PORT", "8769"))
BRIDGE_VERSION = "1.3.1"
_bridge = None

# Shared-token auth skipped: the Chrome extension does not send a token.
# Setting DAVI_BRIDGE_TOKEN would drop existing clients. Leave unset.
# If we add auth later, bump the extension and send the token on hello.


def _agent_language():
    try:
        from services.i18n import get_language
        return get_language() or "en"
    except Exception:
        return "en"


def _screenshots_dir():
    from services.paths import data_path
    return data_path("screenshots")


def _save_browser_screenshot(data_url):
    if not data_url or not isinstance(data_url, str) or "," not in data_url:
        raise ValueError("Invalid screenshot data")
    header, b64 = data_url.split(",", 1)
    ext = "jpg" if "jpeg" in header or "jpg" in header else "png"
    folder = _screenshots_dir()
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"browser_tab.{ext}")
    with open(path, "wb") as f:
        f.write(base64.b64decode(b64))
    return path


class BrowserBridge:
    def __init__(self, port=PORT):
        self.port = port
        self.ws = None
        self.pending = {}
        self._loop = None
        self._thread = None
        self._connected = False
        self.clients = set()

    def start(self):
        if not WS_AVAILABLE:
            print("[BRIDGE] Cannot start — websockets package missing")
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"[BRIDGE] Starting WebSocket server on ws://localhost:{self.port}")

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception as e:
            print(f"[BRIDGE] Server error: {e}")

    async def _serve(self):
        servers = []
        last_err = None
        for host in ("127.0.0.1", "::1"):
            try:
                srv = await websockets.server.serve(self._handler, host, self.port)
                servers.append(srv)
                print(f"[BRIDGE] listening on {host}:{self.port}")
            except OSError as e:
                last_err = e
                print(f"[BRIDGE] skip {host}:{self.port} ({e})")
        if not servers:
            raise last_err or OSError(f"Could not bind WebSocket port {self.port}")
        print(f"[BRIDGE] WebSocket server ready on ws://localhost:{self.port}")
        try:
            await asyncio.Future()
        finally:
            for srv in servers:
                srv.close()
                await srv.wait_closed()

    def _status_payload(self):
        return {
            "type": "status",
            "agent": True,
            "extension_connected": self.is_connected(),
            "version": BRIDGE_VERSION,
            "port": self.port,
            "language": _agent_language(),
        }

    async def _send_json(self, websocket, payload):
        try:
            await websocket.send(json.dumps(payload))
        except Exception:
            pass

    async def _handler(self, websocket):
        role = "pending"
        claimed = False
        self.clients.add(websocket)

        # Existing extension clients never send hello — treat an idle slot as the extension.
        if self.ws is None:
            self.ws = websocket
            self._connected = True
            claimed = True
            print("[BRIDGE] Chrome extension connected!")

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type")
                if msg_type == "hello":
                    role = data.get("role") or "extension"
                    if role == "status":
                        if claimed and self.ws is websocket:
                            self.ws = None
                            self._connected = False
                            claimed = False
                            print("[BRIDGE] Status client connected")
                    else:
                        self.ws = websocket
                        self._connected = True
                        claimed = True
                        role = "extension"
                        print("[BRIDGE] Chrome extension identified")
                    await self._send_json(websocket, self._status_payload())
                    continue

                if msg_type == "ping":
                    await self._send_json(websocket, {
                        "type": "pong",
                        **self._status_payload(),
                    })
                    continue

                req_id = data.get("id")
                if req_id and req_id in self.pending:
                    if self.ws is None or role == "extension":
                        self.ws = websocket
                        self._connected = True
                        claimed = True
                        role = "extension"
                    future = self.pending[req_id]
                    if not future.done():
                        future.set_result(data.get("result", {}))
        except Exception as e:
            print(f"[BRIDGE] Connection closed: {e}")
        finally:
            self.clients.discard(websocket)
            if self.ws is websocket:
                self._connected = False
                self.ws = None
                print("[BRIDGE] Chrome extension disconnected")

    def is_connected(self):
        return self._connected and self.ws is not None

    def send_command(self, command, params=None, timeout=10):
        if not self.is_connected():
            return {"success": False, "error": "Chrome extension not connected. Install the DAVI extension and open Chrome."}
        if not self._loop:
            return {"success": False, "error": "Bridge not running"}

        req_id = str(uuid.uuid4())
        future = self._loop.create_future()
        self.pending[req_id] = future

        msg = json.dumps({"id": req_id, "command": command, "params": params or {}})

        try:
            asyncio.run_coroutine_threadsafe(self.ws.send(msg), self._loop)
        except Exception as e:
            self.pending.pop(req_id, None)
            return {"success": False, "error": f"Send failed: {e}"}

        try:
            coro = asyncio.wait_for(future, timeout)
            result = asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout + 2)
            return self._normalize_result(command, result)
        except TimeoutError:
            return {"success": False, "error": "Command timed out"}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            self.pending.pop(req_id, None)

    def _normalize_result(self, command, result):
        if not isinstance(result, dict):
            return result
        if command in ("take_screenshot", "screenshot") and result.get("screenshot"):
            try:
                path = _save_browser_screenshot(result["screenshot"])
                cleaned = {k: v for k, v in result.items() if k != "screenshot"}
                cleaned["path"] = path
                cleaned["message"] = f"Tab screenshot saved: {path}"
                cleaned["success"] = True
                return cleaned
            except Exception as e:
                cleaned = {k: v for k, v in result.items() if k != "screenshot"}
                cleaned["success"] = False
                cleaned["error"] = f"Screenshot save failed: {e}"
                return cleaned
        return result


def get_bridge():
    global _bridge
    if _bridge is None:
        _bridge = BrowserBridge()
        _bridge.start()
    return _bridge


def bridge_command(command, params=None, timeout=10):
    b = get_bridge()
    return b.send_command(command, params, timeout)


def is_bridge_connected():
    global _bridge
    if _bridge is None:
        return False
    return _bridge.is_connected()
