"""Read text off the screen with the OCR engine built into Windows.

Asking Claude "where is the Save button" costs a round trip and a few cents;
Windows.Media.Ocr answers the same question locally in well under a second and
gives exact pixel boxes. Vision stays as the fallback for anything that is not
literally text on screen.
"""
import asyncio
import re
import threading

_LOOP = None
_LOOP_LOCK = threading.Lock()
_ENGINE = None
_ENGINE_TRIED = False


def _loop():
    """One private event loop: WinRT calls are async and we are called from threads."""
    global _LOOP
    with _LOOP_LOCK:
        if _LOOP is None or _LOOP.is_closed():
            _LOOP = asyncio.new_event_loop()
            threading.Thread(target=_LOOP.run_forever, daemon=True, name="ocr-loop").start()
    return _LOOP


def _run(coro):
    return asyncio.run_coroutine_threadsafe(coro, _loop()).result(timeout=20)


def _engine():
    global _ENGINE, _ENGINE_TRIED
    if _ENGINE_TRIED:
        return _ENGINE
    _ENGINE_TRIED = True
    try:
        from winsdk.windows.media.ocr import OcrEngine
        from winsdk.windows.globalization import Language

        engine = None
        try:
            from services.i18n import get_language
            tag = {"tr": "tr", "en": "en-US", "es": "es", "de": "de", "fr": "fr"}.get(get_language())
            if tag:
                engine = OcrEngine.try_create_from_language(Language(tag))
        except Exception:
            engine = None
        _ENGINE = engine or OcrEngine.try_create_from_user_profile_languages()
    except Exception as e:
        print(f"[OCR] engine unavailable: {e}")
        _ENGINE = None
    return _ENGINE


def ocr_available():
    return _engine() is not None


async def _recognize(pil_img):
    from winsdk.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
    from winsdk.windows.security.cryptography import CryptographicBuffer

    rgba = pil_img.convert("RGBA")
    w, h = rgba.size
    buf = CryptographicBuffer.create_from_byte_array(rgba.tobytes())
    bitmap = SoftwareBitmap.create_copy_from_buffer(buf, BitmapPixelFormat.RGBA8, w, h)
    return await _engine().recognize_async(bitmap)


def read_image(pil_img, origin=(0, 0), scale=1.0):
    """OCR a PIL image. Returns [{text, x, y, left, top, width, height}] in screen pixels."""
    if not ocr_available():
        return []
    try:
        result = _run(_recognize(pil_img))
    except Exception as e:
        print(f"[OCR] recognize failed: {e}")
        return []

    ox, oy = origin
    lines = []
    for line in result.lines:
        words = list(line.words)
        if not words:
            continue
        left = min(wd.bounding_rect.x for wd in words)
        top = min(wd.bounding_rect.y for wd in words)
        right = max(wd.bounding_rect.x + wd.bounding_rect.width for wd in words)
        bottom = max(wd.bounding_rect.y + wd.bounding_rect.height for wd in words)
        lines.append({
            "text": line.text,
            "left": int(ox + left * scale),
            "top": int(oy + top * scale),
            "width": int((right - left) * scale),
            "height": int((bottom - top) * scale),
            "x": int(ox + (left + right) / 2 * scale),
            "y": int(oy + (top + bottom) / 2 * scale),
        })
    return lines


def read_screen(mode=None):
    """OCR the monitor DAVI is watching. Returns (lines, meta)."""
    from services.display import capture_raw
    img, meta = capture_raw(mode)
    lines = read_image(img, origin=(meta["left"], meta["top"]), scale=1.0)
    return lines, meta


_WS = re.compile(r"\s+")


def _norm(s):
    return _WS.sub(" ", (s or "").strip().lower())


def find_text(query, lines=None):
    """Screen boxes whose text matches `query`, best match first."""
    q = _norm(query)
    if not q:
        return []
    if lines is None:
        lines, _meta = read_screen()

    scored = []
    for ln in lines:
        text = _norm(ln["text"])
        if not text:
            continue
        if text == q:
            score = 0
        elif text.startswith(q):
            score = 1
        elif q in text:
            score = 2
        elif _word_subset(q, text):
            score = 3
        else:
            continue
        scored.append((score, len(text), ln))

    scored.sort(key=lambda t: (t[0], t[1]))
    return [ln for _s, _l, ln in scored]


def _word_subset(q, text):
    words = [w for w in q.split() if len(w) > 2]
    return bool(words) and all(w in text for w in words)


def screen_text(limit=120):
    """Flat text of the screen, for 'what does it say' style questions."""
    lines, _meta = read_screen()
    return "\n".join(ln["text"] for ln in lines[:limit])


# "the Save button" and "Save" must hit the same on-screen label.
_FILLER = {
    "the", "a", "an", "this", "that", "on", "in", "at", "of", "for", "to",
    "button", "btn", "icon", "link", "tab", "menu", "item", "field", "box",
    "input", "textbox", "option", "checkbox", "label", "entry", "row",
    "dugmesi", "dugme", "butonu", "buton", "sekmesi", "sekme", "alani", "alan",
}


def _strip_filler(description):
    words = [w for w in re.split(r"[^\w']+", _norm(description)) if w]
    kept = [w for w in words if w not in _FILLER]
    return " ".join(kept or words)


def locate_element(description, lines=None):
    """Screen point for a described element, using its visible text. None if unsure.

    Deliberately conservative: a wrong click is worse than falling through to
    the vision model, so fuzzy word-subset matches are rejected here.
    """
    query = _strip_filler(description)
    if len(query) < 2:
        return None
    hits = find_text(query, lines)
    if not hits:
        return None

    best = hits[0]
    exact = _norm(best["text"]) == query
    if not exact and len(hits) > 1 and _norm(hits[1]["text"]) != query:
        # Several plausible labels and none of them exact — let vision decide.
        if best["width"] * best["height"] and _norm(hits[1]["text"]) == _norm(best["text"]):
            pass
        else:
            return None

    try:
        from services.windows_ops import point_is_overlay
        if point_is_overlay(best["x"], best["y"]):
            return None
    except Exception:
        pass
    return best["x"], best["y"], best["text"]
