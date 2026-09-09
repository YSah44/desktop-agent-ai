"""Privacy blocklist: window-title fragments for apps Aemyos must never screenshot
(bank, password manager, private chats). Stored in .env as DAVI_SCREEN_BLOCKLIST."""
import os

ENV_KEY = "DAVI_SCREEN_BLOCKLIST"


def blocklist():
    raw = os.environ.get(ENV_KEY, "") or ""
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def is_blocked(window_title):
    title = (window_title or "").lower()
    if not title:
        return False
    return any(p in title for p in blocklist())


def set_blocklist(items):
    """Persist a new list (iterable of strings or a comma string)."""
    if isinstance(items, str):
        items = items.split(",")
    cleaned = []
    for p in items:
        p = str(p).strip()
        if p and p.lower() not in [c.lower() for c in cleaned]:
            cleaned.append(p)
    value = ", ".join(cleaned)
    try:
        from config import save_env
        save_env(**{ENV_KEY: value})
    except Exception:
        os.environ[ENV_KEY] = value
    return cleaned
