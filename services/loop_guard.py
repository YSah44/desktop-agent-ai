"""Stop the agent from repeating the same click forever."""

SAME_LIMIT = 5
THINK_AFTER = 5

_SKIP = {"listen", "answer", "remember", "notify", "wait"}


def fingerprint(commands):
    """Stable signature of one model turn (ignores listen/answer)."""
    parts = []
    for raw in commands or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("command") or "").strip().lower()
        if not name or name in _SKIP:
            continue
        params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
        if name in ("click_ui", "move_cursor_to_element", "find_control", "browser_click"):
            parts.append((
                name,
                str(params.get("name") or "").strip().lower(),
                str(params.get("type") or "").strip().lower(),
            ))
        elif name in ("double_click", "mouse_button", "triple_click"):
            parts.append((name, str(params.get("button") or "left").strip().lower()))
        elif name in ("move_cursor_absolute", "move_cursor"):
            parts.append((name,))
        elif name in ("enter_text", "type_text"):
            text = str(params.get("text") or params.get("content") or "")[:80].lower()
            parts.append((name, text))
        else:
            parts.append((name,))
    return tuple(parts)


def describe_fingerprint(fp):
    bits = []
    for part in fp or ():
        if not part:
            continue
        name = part[0]
        extra = ", ".join(str(x) for x in part[1:] if x)
        bits.append(f"{name}({extra})" if extra else name)
    return " + ".join(bits) or "the same click"


def bump_streak(prev_fp, prev_n, commands):
    fp = fingerprint(commands)
    if not fp:
        return prev_fp, 0
    if fp == prev_fp:
        return fp, int(prev_n or 0) + 1
    return fp, 1


def stuck_decision(streak, fp, thought_for):
    """'think' once after SAME_LIMIT repeats, then 'stop' if it repeats again."""
    if not fp or int(streak or 0) < SAME_LIMIT:
        return None
    if thought_for != fp:
        return "think"
    return "stop"


def think_prompt(fp, streak):
    label = describe_fingerprint(fp)
    return (
        f"STUCK. You already sent this exact action {streak} times: {label}. "
        "The screenshot shows it did not finish the task.\n"
        "DO NOT send that same command again.\n"
        "Pause and say why it failed in one sentence, then pick a DIFFERENT method:\n"
        "- Folder/file dialog: type the full folder path in the filename/address box and press Enter, "
        "or click Include Folder / Select Folder / OK. Do not keep double-clicking the same folder. "
        "If it is already highlighted, confirm it.\n"
        "- Named control: click_ui with the exact visible label.\n"
        "- Keyboard shortcut if one exists.\n"
        "If you still cannot do it, tell the user why and send listen."
    )
