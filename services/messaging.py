"""Send a chat message through a desktop messenger (WhatsApp / Telegram Desktop)
by driving its own window: search box → contact → message box → Enter.
No APIs, no accounts: the user's installed app does the sending."""
import re
import time

APPS = {
    "whatsapp": {
        "window": "WhatsApp",
        "search": ["Search or start a new chat", "Search or start new chat", "Search"],
        "box": ["Type a message", "Type a message…"],
    },
    "telegram": {
        "window": "Telegram",
        "search": ["Search"],
        "box": ["Write a message...", "Write a message…", "Message"],
    },
}

_APP_WORDS = {"whatsapp": "whatsapp", "wp": "whatsapp", "telegram": "telegram", "tg": "telegram"}

# "whatsapp Ahmet: I'm late" · "tell Ahmet on whatsapp: I'm late" · "send Ahmet a whatsapp message: I'm late"
_EN = [
    re.compile(r"^(?:on\s+)?(?P<app>whatsapp|wp|telegram|tg)(?!')\s*[:,]?\s*(?P<who>[^:']{1,40}?)\s*:\s*(?P<msg>.+)$", re.I),
    re.compile(r"^(?:tell|message|text|write(?:\s+to)?|send)\s+(?P<who>[^:]{1,40}?)\s+(?:on|via|in)\s+(?P<app>whatsapp|wp|telegram|tg)\s*(?:saying|that)?\s*:\s*(?P<msg>.+)$", re.I),
    re.compile(r"^send\s+(?P<who>[^:]{1,40}?)\s+an?\s+(?P<app>whatsapp|telegram)\s+message\s*(?:saying|that)?\s*:\s*(?P<msg>.+)$", re.I),
]
# "whatsapp'ta Ahmet'e yaz: geç kalıyorum" · "Ahmet'e whatsapp'tan mesaj at: ..."
_TR = [
    re.compile(r"^(?P<app>whatsapp|wp|telegram|tg)\s*(?:'?(?:ta|da|tan|dan))?\s+(?P<who>[^:]{1,40}?)\s*'?(?:e|a|ye|ya)\s+(?:yaz|mesaj at|mesaj gonder|gonder)\s*:\s*(?P<msg>.+)$", re.I),
    re.compile(r"^(?P<who>[^:]{1,40}?)\s*'?(?:e|a|ye|ya)\s+(?P<app>whatsapp|wp|telegram|tg)\s*(?:'?(?:ta|da|tan|dan))?\s+(?:yaz|mesaj at|mesaj gonder|gonder)\s*:\s*(?P<msg>.+)$", re.I),
]


def _fold(text):
    table = str.maketrans({"ı": "i", "İ": "i", "ğ": "g", "Ğ": "g", "ü": "u", "Ü": "u", "ş": "s", "Ş": "s",
                           "ö": "o", "Ö": "o", "ç": "c", "Ç": "c", "’": "'"})
    return re.sub(r"\s+", " ", (text or "").strip().translate(table))


def parse_request(text):
    """Return {"app", "who", "msg"} for an explicit chat request, else None.
    The message keeps the user's original casing/characters."""
    raw = (text or "").strip()
    folded = _fold(raw)
    for pat in _TR + _EN:
        m = pat.match(folded)
        if m:
            app = _APP_WORDS.get(m.group("app").lower())
            who = m.group("who").strip(" ,")
            msg_folded = m.group("msg").strip()
            # take the message from the raw text after the last ':' so Turkish characters survive
            msg = raw.rsplit(":", 1)[1].strip() if ":" in raw else msg_folded
            if app and who and msg:
                return {"app": app, "who": who, "msg": msg}
    return None


def _type(text):
    import pyautogui
    import pyperclip
    # Clipboard paste keeps Unicode intact; typewrite drops non-ASCII.
    old = None
    try:
        old = pyperclip.paste()
    except Exception:
        pass
    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.15)
    if old is not None:
        try:
            pyperclip.copy(old)
        except Exception:
            pass


def _click_first(names, control_type):
    from services.win_uia import click_control
    for n in names:
        r = click_control(n, control_type=control_type)
        if r.get("success"):
            return r
    return {"success": False, "message": f"no control among {names}"}


def send_message(app, who, msg, send=True):
    import pyautogui
    from services import windows_ops
    app = (app or "whatsapp").lower()
    spec = APPS.get(app)
    if not spec:
        return {"success": False, "message": f"Unknown messenger: {app}"}
    if not who or not msg:
        return {"success": False, "message": "Need a contact and a message"}
    f = windows_ops.focus_window(spec["window"])
    if not f.get("success"):
        return {"success": False, "message": f"{spec['window']} is not open"}
    time.sleep(0.6)
    r = _click_first(spec["search"], "Edit")
    if not r.get("success"):
        return {"success": False, "message": f"Search box not found in {spec['window']}"}
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "a")
    _type(who)
    time.sleep(1.2)
    pyautogui.press("enter")
    time.sleep(1.0)
    r = _click_first(spec["box"], "Edit")
    if not r.get("success"):
        return {"success": False, "message": f"Chat with '{who}' did not open (message box not found)"}
    time.sleep(0.2)
    _type(msg)
    time.sleep(0.2)
    if send:
        pyautogui.press("enter")
        return {"success": True, "message": f"Sent to {who} on {spec['window']}: {msg}", "who": who, "app": app}
    return {"success": True, "message": f"Typed for {who} on {spec['window']} (not sent): {msg}", "who": who, "app": app}
