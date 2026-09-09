"""Telegram remote control. The owner texts the bot from their phone, Aemyos runs it
as a normal command and replies in the same chat. Official Bot API over long polling:
free, no server, no webhook. Only the paired chat id is accepted."""
import os
import random
import threading
import time

import requests

_API = "https://api.telegram.org/bot{token}/{method}"
_token = ""
_owner = None
_pair_code = ""
_enqueue = None
_running = False
_active_until = 0.0
ACTIVE_WINDOW_SEC = 180


def _call(method, http_timeout=35, **params):
    r = requests.post(_API.format(token=_token, method=method), json=params, timeout=http_timeout)
    return r.json()


def send(text, chat_id=None):
    cid = chat_id or _owner
    if not _token or not cid or not text:
        return
    try:
        _call("sendMessage", chat_id=cid, text=str(text)[:4000])
    except Exception as e:
        print(f"[TG] send failed: {e}")


def send_photo(path, caption="", chat_id=None):
    cid = chat_id or _owner
    if not _token or not cid or not os.path.isfile(path):
        return
    try:
        with open(path, "rb") as f:
            requests.post(
                _API.format(token=_token, method="sendPhoto"),
                data={"chat_id": cid, "caption": caption[:1000]},
                files={"photo": f},
                timeout=60,
            )
    except Exception as e:
        print(f"[TG] photo failed: {e}")


def is_paired():
    return _owner is not None


def pairing_code():
    return _pair_code


def is_active():
    """True shortly after a Telegram command, so replies are mirrored to the phone."""
    return time.time() < _active_until


def notify(text):
    """Reply sink: mirror Aemyos's spoken/shown replies while a phone command is in flight."""
    if is_active():
        send(text)


def _screenshot_path():
    from services.screenshot_utils import save_screenshot
    return save_screenshot()


def _handle(msg):
    global _owner, _active_until
    chat = msg.get("chat") or {}
    cid = chat.get("id")
    text = (msg.get("text") or "").strip()
    if cid is None or not text:
        return
    if _owner is None:
        code = text.replace("/start", "").strip()
        if code and code == _pair_code:
            _owner = int(cid)
            try:
                from config import save_env
                save_env(DAVI_TELEGRAM_CHAT_ID=str(_owner))
            except Exception:
                pass
            send("Paired with Aemyos. Send any command, /screen for a screenshot, /status for state.", cid)
            print(f"[TG] paired with chat {cid}")
        else:
            send("Not paired. Send the pairing code shown in Aemyos (Settings → Telegram).", cid)
        return
    if int(cid) != int(_owner):
        return
    low = text.lower()
    if low in ("/screen", "/ss", "/screenshot"):
        try:
            send_photo(_screenshot_path(), "Aemyos · current screen")
        except Exception as e:
            send(f"Screenshot failed: {e}")
        return
    if low in ("/status", "/ping"):
        send("Aemyos is running and listening.")
        return
    if low.startswith("/start"):
        send("Already paired. Just type a command.")
        return
    _active_until = time.time() + ACTIVE_WINDOW_SEC
    send(f"▶ {text}")
    if _enqueue:
        _enqueue(text)


def _loop():
    offset = None
    while _running:
        try:
            r = _call("getUpdates", http_timeout=60, offset=offset, timeout=30, allowed_updates=["message"])
            for u in r.get("result") or []:
                offset = int(u["update_id"]) + 1
                try:
                    _handle(u.get("message") or {})
                except Exception as e:
                    print(f"[TG] handler: {e}")
        except Exception as e:
            print(f"[TG] poll: {e}")
            time.sleep(5)


def start(token, owner_chat_id="", enqueue=None):
    """Start polling in a daemon thread. Returns the pairing code if not paired yet."""
    global _token, _owner, _pair_code, _enqueue, _running
    _token = (token or "").strip()
    if not _token:
        return ""
    _enqueue = enqueue
    try:
        _owner = int(str(owner_chat_id).strip()) if str(owner_chat_id).strip() else None
    except ValueError:
        _owner = None
    _pair_code = "" if _owner else f"{random.randint(100000, 999999)}"
    _running = True
    threading.Thread(target=_loop, name="aemyos-telegram", daemon=True).start()
    return _pair_code


def stop():
    global _running
    _running = False
