"""Handlers for UIA, window, file-search, and guarded system commands."""
from services.safety import is_confirmed
from services.windows_ops import (
    list_windows, format_window_list, manage_window, focus_window, switch_app,
    find_files, delete_file, empty_recycle, shutdown_pc, get_foreground_title,
    target_hwnd,
)
from services.win_uia import click_control, find_control, uia_available
from services.display import describe_layout


def handle(command):
    name = command.get("command")
    params = command.get("params") or {}
    handler = _HANDLERS.get(name)
    if handler is None:
        return None
    try:
        out = handler(params, command)
        if isinstance(out, dict):
            out.pop("_el", None)
            out.pop("_pwa", None)
            hits = out.get("hits")
            if isinstance(hits, list):
                out["hits"] = [
                    {k: v for k, v in h.items() if not str(k).startswith("_")}
                    for h in hits if isinstance(h, dict)
                ]
        return out
    except Exception as e:
        return {"success": False, "message": f"{name} error: {e}"}


def _click_ui(params, command):
    target = params.get("name") or params.get("text") or params.get("title") or ""
    ctype = params.get("type") or params.get("control_type") or params.get("controlType")
    button = params.get("button", "left")
    if not target:
        return {"success": False, "message": "click_ui requires params.name"}

    uia_result = click_control(target, control_type=ctype, button=button, retries=1)
    if uia_result.get("success"):
        return uia_result

    # Vision fallback + click, retry once.
    from services.find_ui import move_mouse_to_ui_element
    import pyautogui
    last_err = uia_result.get("message") or "UIA miss"
    for attempt in range(2):
        coords = move_mouse_to_ui_element(target, use_uia=False)
        if coords:
            pyautogui.click(button=button)
            note = f" (vision retry {attempt})" if attempt else ""
            uia_note = "" if uia_available() else " (UIA unavailable)"
            return {
                "success": True,
                "message": f"Vision clicked '{target}' at {coords}{note}{uia_note}",
                "x": coords[0], "y": coords[1],
            }
        last_err = f"Vision could not find '{target}'"
    return {
        "success": False,
        "message": f"click_ui failed for '{target}'. UIA: {uia_result.get('message')}. {last_err}",
    }


def _find_control(params, _command):
    target = params.get("name") or params.get("text") or ""
    ctype = params.get("type") or params.get("control_type")
    aid = params.get("automation_id") or params.get("id")
    result = find_control(name=target or None, control_type=ctype, automation_id=aid)
    if not result.get("success"):
        # Still useful: report target window so the model can recover.
        hwnd, title = target_hwnd()
        result["message"] = (
            result.get("message") or "Not found"
        ) + f" | target window: {title}"
    return result


def _focus_window(params, _command):
    title = params.get("title") or params.get("name") or params.get("window")
    if not title:
        return {"success": False, "message": "focus_window requires params.title"}
    return focus_window(title)


def _list_windows(params, _command):
    wins = list_windows()
    layout = describe_layout()
    fg = get_foreground_title()
    hwnd, target = target_hwnd()
    msg = (
        f"Foreground: {fg}\nAutomation target (skip DAVI): {target}\n"
        f"{layout}\n{format_window_list(wins)}"
    )
    return {"success": True, "message": msg}


def _find_files(params, _command):
    query = params.get("query") or params.get("text") or params.get("name") or ""
    scope = params.get("scope") or params.get("where") or "explorer"
    path = params.get("path") or params.get("location")
    return find_files(query, scope=scope, path=path)


def _search_files(params, _command):
    from services.file_index import search, describe
    query = params.get("query") or params.get("text") or params.get("name") or ""
    kind = params.get("kind") or params.get("type")
    days = params.get("days")
    try:
        days = int(days) if days not in (None, "") else None
    except (TypeError, ValueError):
        days = None
    folder = params.get("folder")
    results = search(query=query, kind=kind, days=days, folder=folder, limit=int(params.get("limit") or 8))
    return {"success": bool(results), "message": describe(results), "results": results}


def _open_path(params, _command):
    from services.file_index import open_path
    return open_path(params.get("path") or params.get("file") or "")


def _send_message(params, _command):
    from services.messaging import send_message
    return send_message(
        params.get("app") or "whatsapp",
        params.get("to") or params.get("contact") or params.get("who") or "",
        params.get("text") or params.get("message") or "",
        send=params.get("send", True) not in (False, "false", "no", 0),
    )


def _manage_window(params, _command):
    action = params.get("action") or ""
    title = params.get("title") or params.get("name")
    r = manage_window(action, title)
    if r.get("success"):
        return {"success": True, "message": r.get("message") or f"Window '{r.get('window')}' → {r.get('action')}"}
    return {"success": False, "message": r.get("error") or r.get("message") or "manage_window failed"}


def _snap_window(params, command):
    params = dict(params)
    params["action"] = params.get("side") or params.get("action") or "left"
    if not str(params["action"]).startswith("snap_"):
        params["action"] = "snap_" + str(params["action"]).replace("snap_", "")
    return _manage_window(params, command)


def _delete_file(params, command):
    if not is_confirmed(command):
        return {"success": False, "message": "REFUSED: delete_file needs confirmed=true"}
    path = params.get("path") or params.get("file") or ""
    return delete_file(path, confirmed=True)


def _empty_recycle(params, command):
    if not is_confirmed(command):
        return {"success": False, "message": "REFUSED: empty_recycle needs confirmed=true"}
    return empty_recycle(confirmed=True)


def _shutdown_pc(params, command):
    if not is_confirmed(command):
        return {"success": False, "message": "REFUSED: shutdown_pc needs confirmed=true"}
    return shutdown_pc(params.get("mode") or params.get("action") or "shutdown", confirmed=True)


def _open_app(params, _command):
    from services.smart_features import open_app_via_start
    name = params.get("name") or params.get("app") or params.get("text") or ""
    return open_app_via_start(name)


def _switch_app(params, _command):
    title = params.get("title") or params.get("name") or params.get("window") or params.get("app") or ""
    mode = params.get("mode") or params.get("action") or "focus"
    if not title and str(mode).lower() in ("focus", ""):
        mode = "alt_tab"
    return switch_app(title or None, mode=mode)


_HANDLERS = {
    "click_ui": _click_ui,
    "find_control": _find_control,
    "focus_window": _focus_window,
    "list_windows": _list_windows,
    "get_running_apps": _list_windows,
    "find_files": _find_files,
    "search_files": _search_files,
    "open_path": _open_path,
    "send_message": _send_message,
    "manage_window": _manage_window,
    "snap_window": _snap_window,
    "delete_file": _delete_file,
    "empty_recycle": _empty_recycle,
    "shutdown_pc": _shutdown_pc,
    "open_app": _open_app,
    "switch_app": _switch_app,
}

EXTENDED_COMMANDS = set(_HANDLERS.keys())
