"""Prefer the Chrome extension over mouse/keyboard when it is connected."""
import re
import time
from urllib.parse import quote_plus, urlparse


_TAB_CACHE = {"at": 0.0, "tabs": None}
_TAB_TTL = 2.5

_NATIVE_CLICK_NAMES = {
    "yes", "no", "ok", "cancel", "allow", "block", "keep", "discard",
    "restore", "save", "open", "close", "reload", "new tab", "extensions",
    "profile", "chrome", "evet", "hayir", "hayır", "iptal", "izin ver",
    "engelle", "kaydet", "ac", "aç", "kapat",
}


def _cmd_name(command):
    return str((command or {}).get("command") or "")


def _cmd_params(command):
    p = (command or {}).get("params")
    return p if isinstance(p, dict) else {}


def youtube_results_url(query):
    return "https://www.youtube.com/results?search_query=" + quote_plus((query or "").strip())


def google_search_url(query):
    return "https://www.google.com/search?q=" + quote_plus((query or "").strip())


def normalize_url(url):
    url = (url or "").strip()
    if not url:
        return ""
    if re.match(r"https?://", url, re.I):
        return url
    if url.startswith("chrome://") or url.startswith("edge://"):
        return url
    return "https://" + url.lstrip("/")


def url_host(url):
    try:
        host = (urlparse(normalize_url(url)).hostname or "").lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _path_and_query(url):
    try:
        p = urlparse(normalize_url(url))
    except Exception:
        return "/", ""
    path = p.path or "/"
    return path, p.query or ""


def is_site_home(url):
    path, query = _path_and_query(url)
    if query:
        return False
    return path in ("", "/", "/feed", "/home")


def _tab_url(tab):
    return (tab or {}).get("url") or ""


def tab_query(params):
    p = params if isinstance(params, dict) else {}
    return str(p.get("query") or p.get("text") or p.get("url") or "").strip()


def tab_matches(tab, query):
    q = (query or "").strip().lower()
    if not q:
        return False
    title = (tab.get("title") or "").lower()
    url = (tab.get("url") or "").lower()
    if q in title or q in url:
        return True
    aliases = {
        "youtube": ("youtube.com", "youtu.be"),
        "yt": ("youtube.com", "youtu.be"),
        "gmail": ("mail.google.com",),
        "google": ("google.com",),
        "github": ("github.com",),
    }
    return any(host in url for host in aliases.get(q, ()))


def format_tabs_message(tabs):
    tabs = tabs or []
    lines = []
    already = []
    seen = set()
    labels = (
        ("youtube.com", "youtube", "YouTube"),
        ("youtu.be", "youtube", "YouTube"),
        ("mail.google.com", "gmail", "Gmail"),
        ("github.com", "github", "GitHub"),
    )
    for t in tabs[:30]:
        title = (t.get("title") or "")[:60]
        url = (t.get("url") or "")[:90]
        tid = t.get("id", "")
        mark = "→" if t.get("active") else " "
        lines.append(f"  {mark} id={tid} {title} | {url}")
        u = (t.get("url") or "").lower()
        for host, key, label in labels:
            if host in u and key not in seen:
                already.append(label)
                seen.add(key)
    hint = ""
    if already:
        hint = (
            f"\nAlready open in this list: {', '.join(already)}. "
            "Use browser_find_tab or browser_switch_tab with the id. Do not open a second copy."
        )
    return f"[TABS] {len(tabs)} open:\n" + "\n".join(lines) + hint


def invalidate_tab_cache():
    _TAB_CACHE["at"] = 0.0
    _TAB_CACHE["tabs"] = None


def get_tabs_cached(ttl=_TAB_TTL, timeout=2.0):
    try:
        from services.browser_bridge import bridge_command, is_bridge_connected
        if not is_bridge_connected():
            return []
    except Exception:
        return []
    now = time.time()
    if _TAB_CACHE["tabs"] is not None and (now - _TAB_CACHE["at"]) < ttl:
        return _TAB_CACHE["tabs"]
    try:
        r = bridge_command("get_tabs", timeout=timeout) or {}
        tabs = r.get("tabs") if r.get("success") else []
    except Exception:
        tabs = []
    tabs = tabs or []
    _TAB_CACHE["at"] = now
    _TAB_CACHE["tabs"] = tabs
    return tabs


def tab_context_lines():
    """Live Chrome tabs for the THIS PC block."""
    try:
        from services.browser_bridge import is_bridge_connected
        if not is_bridge_connected():
            return []
    except Exception:
        return []
    tabs = get_tabs_cached()
    if not tabs:
        return [
            "Chrome extension: CONNECTED — use browser_* for pages. Mouse only if browser_* fails "
            "or for native Chrome UI (profile picker, OS dialogs)."
        ]
    lines = [
        "Chrome extension: CONNECTED — use browser_* for this page. Do not Ctrl+L / click the "
        "address bar / click search boxes. Mouse only if browser_* fails or for native Chrome UI.",
        f"Chrome tabs ({len(tabs)}) — reuse with browser_find_tab / browser_switch_tab:",
    ]
    for t in tabs[:18]:
        mark = "→" if t.get("active") else " "
        title = (t.get("title") or "")[:50]
        url = (t.get("url") or "")[:70]
        lines.append(f"  {mark} id={t.get('id')} {title} | {url}")
    return lines


def find_tab_via_list(bridge_command, params):
    params = params if isinstance(params, dict) else {}
    if params.get("tab_id") is not None:
        return bridge_command("switch_tab", {"tab_id": params["tab_id"]})
    query = tab_query(params)
    if not query:
        return {"success": False, "error": "Provide query or tab_id"}
    listing = bridge_command("get_tabs")
    tabs = listing.get("tabs") or []
    matches = [t for t in tabs if tab_matches(t, query)]
    if not matches:
        return {"success": False, "error": f'No tab matching "{query}"'}
    tab = matches[0]
    sw = bridge_command("switch_tab", {"tab_id": tab["id"]})
    err = str(sw.get("error") or "")
    if sw.get("success"):
        invalidate_tab_cache()
        sw["message"] = f'Switched to: {tab.get("title")} | {tab.get("url")}'
        return sw
    if "Unknown command" in err:
        return {
            "success": False,
            "error": "Tab switch needs the Aemyos Chrome extension reloaded (chrome://extensions).",
        }
    return sw


def bridge_find_tab(bridge_command, params):
    params = params if isinstance(params, dict) else {}
    r = bridge_command("find_tab", params)
    err = str(r.get("error") or "")
    if r.get("success") and "Unknown command" not in err:
        invalidate_tab_cache()
        return r
    if "Unknown command" in err:
        return find_tab_via_list(bridge_command, params)
    if not r.get("success"):
        fb = find_tab_via_list(bridge_command, params)
        if fb.get("success"):
            return fb
    return r


def _best_tab_for_url(tabs, url):
    host = url_host(url)
    if not host:
        return None
    matches = []
    for t in tabs or []:
        th = url_host(_tab_url(t))
        if th == host or (host and host in (_tab_url(t) or "").lower()):
            matches.append(t)
    if not matches:
        return None
    target = normalize_url(url).lower().rstrip("/")
    for t in matches:
        if (_tab_url(t) or "").lower().rstrip("/") == target:
            return t
    for t in matches:
        if t.get("active"):
            return t
    return matches[0]


def _should_navigate_after_switch(tab, url):
    if not url or url.startswith("chrome://"):
        return True
    if is_site_home(url):
        return False
    current = (_tab_url(tab) or "").lower().rstrip("/")
    wanted = normalize_url(url).lower().rstrip("/")
    return current != wanted


def reuse_or_open_url(url, prefer_new=False, bridge_command=None):
    """Switch to an existing tab for this site, or open one via the extension."""
    url = (url or "").strip()
    if not url:
        return {"success": False, "error": "no url"}
    if url in ("chrome://newtab", "about:blank") and prefer_new:
        fn = bridge_command
        if fn is None:
            from services.browser_bridge import bridge_command as fn
        invalidate_tab_cache()
        return fn("new_tab", {"url": url})

    url = normalize_url(url)
    if bridge_command is None:
        from services.browser_bridge import bridge_command as bridge_command

    tabs = []
    listing = bridge_command("get_tabs") or {}
    if listing.get("success"):
        tabs = listing.get("tabs") or []
        _TAB_CACHE["at"] = time.time()
        _TAB_CACHE["tabs"] = tabs

    tab = _best_tab_for_url(tabs, url)
    if tab:
        sw = bridge_command("switch_tab", {"tab_id": tab["id"]})
        if "Unknown command" in str(sw.get("error") or ""):
            sw = find_tab_via_list(bridge_command, {"tab_id": tab["id"]})
        if sw.get("success"):
            invalidate_tab_cache()
            if _should_navigate_after_switch(tab, url):
                r = bridge_command("navigate", {"url": url})
                invalidate_tab_cache()
                if r.get("success"):
                    r["message"] = f"Reused tab, opened {url}"
                return r
            sw["message"] = f'Reused open tab: {tab.get("title")} | {tab.get("url")}'
            return sw

    r = bridge_command("new_tab", {"url": url})
    invalidate_tab_cache()
    return r


def _hotkey_set(command):
    p = _cmd_params(command)
    keys = p.get("keys") or p.get("key")
    if isinstance(keys, str):
        keys = [k.strip() for k in keys.replace("+", " ").split() if k.strip()]
    return frozenset(str(k).lower().strip() for k in (keys or []) if k)


def _is_enter_submit(command):
    name = _cmd_name(command)
    p = _cmd_params(command)
    if name == "press_key":
        return "enter" in str(p.get("key") or p.get("keys") or "").lower()
    if name == "press_hotkey":
        return _hotkey_set(command) in (frozenset({"enter"}), frozenset({"return"}))
    return False


def _is_search_click(command):
    name = _cmd_name(command)
    if name not in ("browser_click", "click_ui", "move_cursor_to_element"):
        return False
    p = _cmd_params(command)
    blob = " ".join(str(p.get(k) or "") for k in ("selector", "id", "text", "name", "label")).lower()
    return "search" in blob or "#search" in blob or blob in ("q", "ara")


def _looks_like_url(text):
    t = (text or "").strip()
    if re.match(r"https?://", t, re.I):
        return True
    if " " in t:
        return False
    return bool(re.match(r"[\w-]+\.[\w.-]+(/\S*)?$", t))


def query_to_url(text, tabs=None):
    raw = (text or "").strip()
    if not raw:
        return ""
    if _looks_like_url(raw):
        return normalize_url(raw)
    active = next((t for t in (tabs or []) if t.get("active")), None)
    host = url_host(_tab_url(active)) if active else ""
    if host in ("youtube.com", "youtu.be"):
        return youtube_results_url(raw)
    if host in ("google.com", "bing.com"):
        return google_search_url(raw)
    lowered = raw.lower()
    if "youtube" in lowered or "youtu.be" in lowered:
        q = re.sub(r"\b(on\s+)?youtube\b", "", raw, flags=re.I).strip()
        return youtube_results_url(q or raw)
    return google_search_url(raw)


def _replace_indexes(cmds, drop, insert_at, new_cmd):
    out = []
    inserted = False
    for k, cmd in enumerate(cmds):
        if k in drop:
            if not inserted:
                out.append(new_cmd)
                inserted = True
            continue
        out.append(cmd)
    if not inserted:
        out.insert(insert_at, new_cmd)
    return out


def _rewrite_search_box(commands):
    cmds = list(commands)
    n = len(cmds)
    for i, c in enumerate(cmds):
        if not _is_search_click(c):
            continue
        text = None
        drop = {i}
        for j in range(i + 1, min(i + 6, n)):
            name = _cmd_name(cmds[j])
            if name == "wait":
                drop.add(j)
                continue
            if name == "enter_text" and not text:
                text = str(_cmd_params(cmds[j]).get("text") or "").strip()
                if text:
                    drop.add(j)
                continue
            if text and _is_enter_submit(cmds[j]):
                drop.add(j)
                break
            if name.startswith("browser_") and name != "browser_click":
                break
        if not text:
            continue
        blob = " ".join(
            str(_cmd_params(c).get(k) or "")
            for k in ("selector", "id", "text", "name", "label")
        ).lower()
        if "search_query" in blob or "#search" in blob or "id='search'" in blob or 'id="search"' in blob:
            dest = youtube_results_url(text)
        else:
            dest = query_to_url(text, get_tabs_cached())
        return _replace_indexes(cmds, drop, i, {
            "command": "browser_navigate",
            "params": {"url": dest},
        })
    return cmds


def _rewrite_address_bar(commands, tabs):
    cmds = list(commands)
    n = len(cmds)
    for i, c in enumerate(cmds):
        if _cmd_name(c) != "press_hotkey":
            continue
        keys = _hotkey_set(c)
        if keys != frozenset({"ctrl", "l"}) and keys != frozenset({"control", "l"}):
            continue
        text = None
        drop = {i}
        for j in range(i + 1, min(i + 6, n)):
            name = _cmd_name(cmds[j])
            if name == "wait":
                drop.add(j)
                continue
            if name == "enter_text" and not text:
                text = str(_cmd_params(cmds[j]).get("text") or "").strip()
                if text:
                    drop.add(j)
                continue
            if text and _is_enter_submit(cmds[j]):
                drop.add(j)
                break
            break
        if not text:
            continue
        return _replace_indexes(cmds, drop, i, {
            "command": "browser_navigate",
            "params": {"url": query_to_url(text, tabs)},
        })
    return cmds


def _rewrite_browser_hotkeys(commands):
    mapping = {
        frozenset({"ctrl", "t"}): ("browser_new_tab", {}),
        frozenset({"control", "t"}): ("browser_new_tab", {}),
        frozenset({"ctrl", "w"}): ("browser_close_tab", {}),
        frozenset({"control", "w"}): ("browser_close_tab", {}),
        frozenset({"ctrl", "r"}): ("browser_reload_tab", {}),
        frozenset({"control", "r"}): ("browser_reload_tab", {}),
        frozenset({"f5"}): ("browser_reload_tab", {}),
        frozenset({"alt", "left"}): ("browser_go_back", {}),
        frozenset({"alt", "right"}): ("browser_go_forward", {}),
    }
    out = []
    i = 0
    cmds = list(commands)
    while i < len(cmds):
        c = cmds[i]
        if _cmd_name(c) == "press_hotkey":
            mapped = mapping.get(_hotkey_set(c))
            if mapped:
                name, params = mapped
                url = ""
                drop_extra = 0
                if name == "browser_new_tab":
                    j = i + 1
                    if j < len(cmds) and _cmd_name(cmds[j]) == "wait":
                        j += 1
                        drop_extra += 1
                    if j < len(cmds) and _cmd_name(cmds[j]) == "enter_text":
                        url = str(_cmd_params(cmds[j]).get("text") or "").strip()
                        drop_extra += 1
                        k = j + 1
                        if k < len(cmds) and _cmd_name(cmds[k]) == "wait":
                            drop_extra += 1
                            k += 1
                        if k < len(cmds) and _is_enter_submit(cmds[k]):
                            drop_extra += 1
                    if url:
                        params = {"url": query_to_url(url) if not _looks_like_url(url) else normalize_url(url)}
                out.append({"command": name, "params": params})
                i += 1 + drop_extra
                continue
        out.append(c)
        i += 1
    return out


def chrome_is_front():
    try:
        from services.windows_ops import get_foreground_title
        title = (get_foreground_title() or "").lower()
        return "chrome" in title
    except Exception:
        return False


def _rewrite_mouse_to_browser(commands):
    cmds = list(commands)
    out = []
    i = 0
    while i < len(cmds):
        c = cmds[i]
        name = _cmd_name(c)
        p = _cmd_params(c)
        label = str(p.get("name") or p.get("text") or p.get("label") or "").strip()
        nxt = cmds[i + 1] if i + 1 < len(cmds) else None

        if name == "move_cursor_to_element" and nxt and _cmd_name(nxt) == "mouse_button" and label:
            if label.lower() not in _NATIVE_CLICK_NAMES:
                out.append({"command": "browser_click", "params": {"text": label}})
                i += 2
                continue

        if name == "click_ui" and label:
            ctype = str(p.get("type") or "").lower()
            if label.lower() not in _NATIVE_CLICK_NAMES and ctype in (
                "hyperlink", "link", "listitem",
            ):
                out.append({"command": "browser_click", "params": {"text": label}})
                i += 1
                continue

        out.append(c)
        i += 1
    return out


def _rewrite_open_url(commands):
    out = []
    for c in commands:
        if _cmd_name(c) == "open_url":
            url = str(_cmd_params(c).get("url") or "").strip()
            out.append({"command": "browser_navigate", "params": {"url": url}})
        else:
            out.append(c)
    return out


def rewrite_chrome_commands(commands, bridge_connected=None, chrome_front=None):
    """Turn mouse/keyboard Chrome steps into extension commands when the bridge is up."""
    cmds = [c for c in (commands or []) if isinstance(c, dict)]
    if not cmds:
        return cmds
    cmds = _rewrite_search_box(cmds)
    if bridge_connected is None:
        try:
            from services.browser_bridge import is_bridge_connected
            bridge_connected = bool(is_bridge_connected())
        except Exception:
            bridge_connected = False
    if not bridge_connected:
        return cmds
    in_browser_batch = any(
        _cmd_name(c).startswith("browser_") or _cmd_name(c) == "open_url"
        for c in cmds
    )
    front = chrome_is_front() if chrome_front is None else bool(chrome_front)
    if not front and not in_browser_batch:
        return cmds
    tabs = []
    try:
        tabs = get_tabs_cached()
    except Exception:
        tabs = []
    before = [(_cmd_name(c), _cmd_params(c)) for c in cmds]
    cmds = _rewrite_address_bar(cmds, tabs)
    cmds = _rewrite_browser_hotkeys(cmds)
    if front or in_browser_batch:
        cmds = _rewrite_mouse_to_browser(cmds)
        cmds = _rewrite_open_url(cmds)
    after = [(_cmd_name(c), _cmd_params(c)) for c in cmds]
    if after != before:
        names = [c.get("command") for c in cmds]
        print(f"[CHROME] using extension: {names}")
    return cmds


# Aliases used by older tests / execute_funcs
_youtube_results_url = youtube_results_url
_tab_matches = tab_matches
_format_tabs_message = format_tabs_message
_bridge_find_tab = bridge_find_tab
_rewrite_youtube_search = _rewrite_search_box
