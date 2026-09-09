"""Local owner face memory. Haar detect + LBP/intensity match. Stays on disk.

Webcam frames never leave the PC for enrollment. memory.json only stores
whether a face is saved; embeddings live in faces/owner.npz.
"""
import os
import threading
import time
from datetime import datetime

import numpy as np

from services.paths import DATA_DIR as _ROOT
_SIZE = 96
_MATCH = 0.90
_MATCH_SECOND = 0.84
_STABLE = 0.93
_MIN_FACE = 80
_MAX_SAMPLES = 5
_OBSERVE_GAP = 0.40
_HIT_FRAMES = 3
_MISS_FRAMES = 4
_DOMINANT = 2.2
_EMBED_VERSION = 2

_lock = threading.Lock()
_cascade = None
_embeds = None
_loaded = False
_session_seen = False
_session_enrolled = False
_pending = []
_last_observe = 0.0
_last_hit = None
_last_face = False
_face_count = 0
_hit_streak = 0
_miss_streak = 0
_event = None


def _faces_dir():
    override = (os.environ.get("DAVI_FACES_DIR") or "").strip()
    return override or os.path.join(_ROOT, "faces")


def _npz_path():
    return os.path.join(_faces_dir(), "owner.npz")


def _cascade_detector():
    global _cascade
    if _cascade is not None:
        return _cascade
    import cv2
    for name in ("haarcascade_frontalface_default.xml", "haarcascade_frontalface_alt2.xml"):
        path = os.path.join(cv2.data.haarcascades, name)
        if os.path.isfile(path):
            det = cv2.CascadeClassifier(path)
            if not det.empty():
                _cascade = det
                return _cascade
    _cascade = False
    return None


def _prepare(gray):
    import cv2
    face = cv2.resize(gray, (_SIZE, _SIZE))
    return cv2.equalizeHist(face)


def _lbp(img):
    h, w = img.shape
    out = np.zeros((h - 2, w - 2), dtype=np.uint8)
    c = img[1:-1, 1:-1]
    for i, (dy, dx) in enumerate(((-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1))):
        n = img[1 + dy:h - 1 + dy, 1 + dx:w - 1 + dx]
        out |= ((n >= c).astype(np.uint8) << i)
    return out


def embed_face(gray96):
    """Spatial LBP + coarse intensity. Grid keeps two people from looking alike."""
    cells = 4
    bins = 32
    lbp = _lbp(gray96)
    ch = max(1, lbp.shape[0] // cells)
    cw = max(1, lbp.shape[1] // cells)
    parts = []
    for i in range(cells):
        for j in range(cells):
            cell = lbp[i * ch:(i + 1) * ch, j * cw:(j + 1) * cw]
            if cell.size == 0:
                parts.append(np.zeros(bins, dtype=np.float32))
                continue
            hist, _ = np.histogram(cell.ravel(), bins=bins, range=(0, 256), density=True)
            parts.append(hist.astype(np.float32))
    small = gray96[::8, ::8].astype(np.float32) / 255.0
    return np.concatenate(parts + [small.ravel() * 0.30])


def cosine(a, b):
    a = np.asarray(a, dtype=np.float32).ravel()
    b = np.asarray(b, dtype=np.float32).ravel()
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na < 1e-8 or nb < 1e-8:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _work_bgr(bgr, max_w=640):
    import cv2
    if bgr is None or getattr(bgr, "size", 0) == 0:
        return None
    h, w = bgr.shape[:2]
    if w > max_w and w > 0:
        scale = max_w / float(w)
        bgr = cv2.resize(bgr, (max_w, max(1, int(h * scale))))
    return bgr


def _boxes(gray):
    det = _cascade_detector()
    if not det:
        return []
    found = det.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=6, minSize=(_MIN_FACE, _MIN_FACE)
    )
    if found is None or len(found) == 0:
        return []
    return [(int(x), int(y), int(w), int(h)) for x, y, w, h in found]


def _crop_box(gray, box):
    x, y, w, h = box
    if w < _MIN_FACE or h < _MIN_FACE:
        return None
    pad = int(min(w, h) * 0.10)
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(gray.shape[1], x + w + pad)
    y1 = min(gray.shape[0], y + h + pad)
    crop = gray[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    return _prepare(crop)


def _pick_face(boxes):
    """One face, or the largest if it clearly dominates. Else None (crowd)."""
    if not boxes:
        return None, 0
    ranked = sorted(boxes, key=lambda r: r[2] * r[3], reverse=True)
    count = len(ranked)
    if count == 1:
        return ranked[0], 1
    a = ranked[0][2] * ranked[0][3]
    b = ranked[1][2] * ranked[1][3]
    if b > 0 and (a / float(b)) >= _DOMINANT:
        return ranked[0], count
    return None, count


def detect_face_gray(bgr):
    """Largest frontal face as a prepared 96x96 crop, or None if crowded."""
    crop, _count = face_scene(bgr)
    return crop


def face_scene(bgr):
    """crop, face_count. count>=2 and crop is None means do not guess."""
    import cv2
    work = _work_bgr(bgr)
    if work is None:
        return None, 0
    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    box, count = _pick_face(_boxes(gray))
    if box is None:
        return None, count
    return _crop_box(gray, box), count


def owner_name():
    try:
        from services.personal import known_user_name
        return (known_user_name(persist=False) or "").strip()
    except Exception:
        return ""


def _memory_face(enrolled, samples):
    try:
        from services.execute_funcs import load_memory, save_memory
        mem = load_memory()
        user = dict(mem.get("user") or {})
        if enrolled:
            user["face"] = {
                "enrolled": True,
                "samples": int(samples),
                "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
        else:
            user.pop("face", None)
        mem["user"] = user
        save_memory(mem)
    except Exception as exc:
        print(f"[FACE] memory: {exc}")


def _load_locked():
    global _embeds, _loaded
    if _loaded:
        return _embeds
    _loaded = True
    path = _npz_path()
    if not os.path.isfile(path):
        _embeds = None
        return None
    try:
        data = np.load(path)
        rows = np.asarray(data["embeds"], dtype=np.float32)
        version = int(data["version"][0]) if "version" in data.files else 1
        probe = embed_face(np.zeros((_SIZE, _SIZE), dtype=np.uint8))
        if rows.ndim != 2 or rows.shape[0] < 1 or version != _EMBED_VERSION or rows.shape[1] != probe.size:
            print("[FACE] old face store ignored — say yüzümü kaydet to save again")
            _embeds = None
            return None
        _embeds = rows
        return _embeds
    except Exception as exc:
        print(f"[FACE] load: {exc}")
        _embeds = None
        return None


def reload_store():
    global _loaded, _embeds
    with _lock:
        _loaded = False
        _embeds = None


def is_enrolled():
    with _lock:
        rows = _load_locked()
        return bool(rows is not None and len(rows) > 0)


def _save_locked(rows):
    global _embeds, _loaded
    os.makedirs(_faces_dir(), exist_ok=True)
    stacked = np.asarray(rows, dtype=np.float32)
    np.savez_compressed(_npz_path(), embeds=stacked, version=np.array([_EMBED_VERSION]))
    _embeds = stacked
    _loaded = True
    _memory_face(True, len(stacked))


def enroll_embeds(vectors, replace=True):
    vecs = [np.asarray(v, dtype=np.float32).ravel() for v in (vectors or []) if v is not None]
    if not vecs:
        return False
    with _lock:
        existing = list(_load_locked() or []) if not replace else []
        merged = existing + vecs
        if len(merged) > _MAX_SAMPLES:
            merged = merged[-_MAX_SAMPLES:]
        _save_locked(merged)
    print(f"[FACE] enrolled {len(merged)} sample(s)")
    return True


def enroll_crops(crops, replace=True):
    return enroll_embeds([embed_face(c) for c in (crops or []) if c is not None], replace=replace)


def _score_rows(vector, rows):
    if rows is None or vector is None or len(rows) == 0:
        return 0.0
    scores = sorted((cosine(vector, row) for row in rows), reverse=True)
    best = scores[0]
    if best < _MATCH:
        return 0.0
    if len(scores) == 1:
        return best
    if scores[1] < _MATCH_SECOND:
        return 0.0
    return best


def best_score(vector):
    with _lock:
        return _score_rows(vector, _load_locked())


def match_embed(vector):
    score = best_score(vector)
    if score >= _MATCH:
        return score
    return None


def forget_face():
    global _embeds, _loaded, _pending, _last_hit, _session_seen, _session_enrolled
    global _hit_streak, _miss_streak, _face_count, _last_face
    path = _npz_path()
    with _lock:
        _embeds = None
        _loaded = True
        _pending = []
        _last_hit = None
        _session_seen = False
        _session_enrolled = False
        _hit_streak = 0
        _miss_streak = 0
        _face_count = 0
        _last_face = False
        try:
            if os.path.isfile(path):
                os.remove(path)
        except Exception as exc:
            print(f"[FACE] forget file: {exc}")
        _memory_face(False, 0)
    print("[FACE] forgot owner face")
    return {"success": True, "key": "face_forgot", "text": ""}


def reset_session():
    global _pending, _session_seen, _session_enrolled, _last_hit, _last_face, _last_observe
    global _hit_streak, _miss_streak, _face_count
    with _lock:
        _pending = []
        _session_seen = False
        _session_enrolled = False
        _last_hit = None
        _last_face = False
        _last_observe = 0.0
        _hit_streak = 0
        _miss_streak = 0
        _face_count = 0


def consume_event():
    global _event
    with _lock:
        ev = _event
        _event = None
        return ev


def last_match():
    with _lock:
        return dict(_last_hit) if _last_hit else None


def seeing_face():
    with _lock:
        return bool(_last_face)


def crowd_in_view():
    with _lock:
        return int(_face_count) >= 2 and not _last_hit


def prompt_line():
    """English context for the model. Not spoken."""
    name = owner_name() or "the owner"
    extra = " The illustrated overlay face is Aemyos, not a person. Never guess identity from the desktop screenshot."
    if not is_enrolled():
        return "Local face memory: none yet. One clear face in the webcam will be saved. If two people are in frame, wait." + extra
    if crowd_in_view():
        return f"Local face memory: more than one face in the webcam. Do not guess who is {name}." + extra
    hit = last_match()
    if hit:
        return f"Local face memory: the webcam face is {name} (recognized). Only greet if that line is current." + extra
    if seeing_face():
        return f"Local face memory: {name} is enrolled, but this webcam face does not match. Do not call them {name}." + extra
    return f"Local face memory: {name} is enrolled, not currently in view." + extra


def ui_state():
    """Overlay label: key, name, tone (ok/warn/dim)."""
    enrolled = is_enrolled()
    name = owner_name()
    if crowd_in_view():
        return {"key": "face_crowd", "name": name, "tone": "warn"}
    if not enrolled:
        if seeing_face():
            return {"key": "face_learning", "name": name, "tone": "ok"}
        return {"key": "face_no_enroll", "name": name, "tone": "dim"}
    if last_match():
        return {"key": "face_known_named" if name else "face_known", "name": name, "tone": "ok"}
    if seeing_face():
        return {"key": "face_unknown", "name": name, "tone": "warn"}
    return {"key": "face_looking", "name": name, "tone": "dim"}


def _set_event(kind, score=0.0):
    global _event
    _event = {
        "kind": kind,
        "name": owner_name(),
        "score": float(score or 0.0),
        "at": time.time(),
    }


def observe_frame(bgr):
    """Called from the webcam thread. Auto-enrolls, then recognizes."""
    global _last_observe, _last_face, _last_hit, _pending, _session_seen, _session_enrolled
    global _face_count, _hit_streak, _miss_streak
    now = time.time()
    with _lock:
        if (now - _last_observe) < _OBSERVE_GAP:
            return
        _last_observe = now
    crop, count = face_scene(bgr)
    with _lock:
        _face_count = int(count)
        _last_face = crop is not None
        if count >= 2 and crop is None:
            _pending = []
            _hit_streak = 0
            _miss_streak += 1
            if _miss_streak >= _MISS_FRAMES:
                _last_hit = None
            return
        if crop is None:
            _pending = []
            _hit_streak = 0
            _miss_streak += 1
            if _miss_streak >= _MISS_FRAMES:
                _last_hit = None
            return
        vec = embed_face(crop)
        rows = _load_locked()
        if rows is None or len(rows) == 0:
            _hit_streak = 0
            if count >= 2:
                _pending = []
                return
            _pending.append(vec)
            if len(_pending) > 8:
                _pending = _pending[-8:]
            if len(_pending) >= 5:
                recent = _pending[-5:]
                if all(cosine(recent[i], recent[i + 1]) >= _STABLE for i in range(4)):
                    _save_locked(recent[-4:])
                    _pending = []
                    _session_enrolled = True
                    _session_seen = True
                    _last_hit = {"score": 1.0, "at": now}
                    _hit_streak = _HIT_FRAMES
                    _miss_streak = 0
                    _set_event("enrolled", 1.0)
                    print("[FACE] auto-enrolled owner")
            return
        score = _score_rows(vec, rows)
        if score >= _MATCH:
            _hit_streak += 1
            _miss_streak = 0
            if _hit_streak >= _HIT_FRAMES:
                _last_hit = {"score": score, "at": now}
                if not _session_seen and not _session_enrolled:
                    _session_seen = True
                    _set_event("recognized", score)
                    print(f"[FACE] recognized owner ({score:.2f})")
        else:
            _hit_streak = 0
            _miss_streak += 1
            if _miss_streak >= _MISS_FRAMES:
                _last_hit = None


def enroll_from_camera(timeout=2.6):
    from services.webcam import grab_bgr, is_on, start

    if not is_on():
        result = start() or {}
        if not result.get("success"):
            return {"success": False, "key": "face_need_cam", "text": ""}
    deadline = time.time() + float(timeout)
    crops = []
    while time.time() < deadline:
        crop, count = face_scene(grab_bgr())
        if crop is not None and count <= 1:
            crops.append(crop)
            if len(crops) >= 4:
                break
        time.sleep(0.18)
    if not crops:
        return {"success": False, "key": "face_none", "text": ""}
    existed = is_enrolled()
    enroll_crops(crops, replace=True)
    with _lock:
        global _session_enrolled, _session_seen, _last_hit, _last_face
        _session_enrolled = True
        _session_seen = True
        _last_hit = {"score": 1.0, "at": time.time()}
        _last_face = True
    name = owner_name()
    if existed:
        return {"success": True, "key": "face_updated", "text": name}
    if name:
        return {"success": True, "key": "face_saved_named", "text": name}
    return {"success": True, "key": "face_saved", "text": ""}


def query_now():
    from services.webcam import grab_bgr, is_on

    if not is_on():
        return {"success": False, "key": "face_need_cam", "text": ""}
    if not is_enrolled():
        return {"success": False, "key": "face_no_enroll", "text": ""}
    crop, count = face_scene(grab_bgr())
    name = owner_name()
    if count >= 2 and crop is None:
        return {"success": False, "key": "face_crowd", "text": ""}
    if crop is not None:
        score = match_embed(embed_face(crop))
        if score is not None:
            with _lock:
                global _last_hit, _last_face, _face_count
                _last_hit = {"score": score, "at": time.time()}
                _last_face = True
                _face_count = count
            return {
                "success": True,
                "key": "face_known_named" if name else "face_known",
                "text": name,
            }
        return {"success": False, "key": "face_unknown", "text": ""}
    hit = last_match()
    if hit and (time.time() - float(hit.get("at") or 0)) < 2.0:
        return {
            "success": True,
            "key": "face_known_named" if name else "face_known",
            "text": name,
        }
    if seeing_face():
        return {"success": False, "key": "face_unknown", "text": ""}
    return {"success": False, "key": "face_none", "text": ""}
