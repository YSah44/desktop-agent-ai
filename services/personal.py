"""Personal memory the user owns: notes, profile, routines, and facts.

Notes and routines are written when they ask. Name, city, likes, and job
go into memory.json. Songs, YouTube titles, and meeting chatter do not.
"""
import re
from datetime import datetime

MAX_NOTES = 60
MAX_ROUTINES = 30
MAX_ROUTINE_STEPS = 20
MAX_FACTS = 20


def _memory_io():
    from services.execute_funcs import load_memory, save_memory
    return load_memory, save_memory


def _fold(text):
    from services.smart_features import _fold_voice
    return _fold_voice(text)


# ── Notes ────────────────────────────────────────────────────────

def add_note(text):
    text = (text or "").strip().rstrip(".")
    if not text:
        return None
    load_memory, save_memory = _memory_io()
    mem = load_memory()
    notes = list(mem.get("notes") or [])
    notes.append({"text": text[:400], "date": datetime.now().strftime("%Y-%m-%d %H:%M")})
    mem["notes"] = notes[-MAX_NOTES:]
    save_memory(mem)
    return text


def list_notes(limit=20):
    load_memory, _ = _memory_io()
    rows = list((load_memory().get("notes") or []))[-limit:]
    out = []
    for row in rows:
        if isinstance(row, dict):
            out.append({"text": str(row.get("text") or ""), "date": str(row.get("date") or "")})
        elif str(row).strip():
            out.append({"text": str(row), "date": ""})
    return [r for r in out if r["text"]]


def delete_note(text):
    load_memory, save_memory = _memory_io()
    mem = load_memory()
    kept = []
    for row in (mem.get("notes") or []):
        value = row.get("text") if isinstance(row, dict) else str(row)
        if value != text:
            kept.append(row)
    mem["notes"] = kept
    save_memory(mem)


def clear_notes():
    load_memory, save_memory = _memory_io()
    mem = load_memory()
    mem["notes"] = []
    save_memory(mem)


_AMBIENT_GAP = 10.0
_ambient_last = {"text": "", "at": 0.0, "track": ""}


def _ambient_similar(a, b):
    aa = " ".join((a or "").lower().split())
    bb = " ".join((b or "").lower().split())
    if not aa or not bb:
        return False
    if aa == bb or aa in bb or bb in aa:
        return True
    wa, wb = set(aa.split()), set(bb.split())
    if len(wa) < 4:
        return False
    return (len(wa & wb) / len(wa)) >= 0.75


def add_ambient_note(text, kind="media", source=""):
    """Do not persist lyrics, tracks, or meeting chatter."""
    return None


def note_now_playing(title, artist=""):
    """Tracks stay in RAM via busy_audio, never memory.json."""
    return None


# ── Life (facts the user told DAVI — not songs) ─────────────────

def _life_bucket(mem):
    life = mem.get("life")
    if not isinstance(life, dict):
        life = {}
    facts = life.get("facts")
    if not isinstance(facts, list):
        facts = []
    mem["life"] = {"facts": facts}
    return mem["life"]


def _clean_title(text):
    return re.sub(r"\s+", " ", (text or "").strip())[:180]


def _title_key(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()[:80]


def observe_media(kind, title, artist=""):
    return None


def observe_meeting(window_title, snippet=""):
    return None


def observe_busy(reason=None):
    return None


def learn_fact(text):
    text = _clean_title(text)
    if len(text) < 4:
        return None
    load_memory, save_memory = _memory_io()
    mem = load_memory()
    life = _life_bucket(mem)
    rows = list(life.get("facts") or [])
    if any(_ambient_similar(text, (r.get("text") if isinstance(r, dict) else str(r)) or "") for r in rows[-12:]):
        return None
    rows.append({"text": text[:200], "at": datetime.now().strftime("%Y-%m-%d %H:%M")})
    life["facts"] = rows[-MAX_FACTS:]
    save_memory(mem)
    print(f"[LIFE] fact: {text[:80]}")
    return text


def harvest_personal(text):
    """Quietly store name / city / likes / job. Does not consume the turn."""
    raw = (text or "").strip()
    if not raw:
        return None
    saved = []
    name = match_set_name(raw)
    if name:
        set_profile("name", name)
        if learn_fact(f"Name: {name}"):
            saved.append(name)
    loc = match_location(raw)
    if loc:
        set_profile("location", loc)
        if learn_fact(f"Lives in {loc}"):
            saved.append(loc)
    role = match_role(raw)
    if role:
        set_profile("role", role)
        if learn_fact(f"Works as {role}"):
            saved.append(role)
    like = match_like(raw)
    if like:
        if learn_fact(f"Likes {like}"):
            saved.append(like)
    return saved or None


def list_life_rows(limit=12):
    load_memory, _ = _memory_io()
    mem = load_memory()
    life = mem.get("life") if isinstance(mem.get("life"), dict) else {}
    out = []
    for row in (life.get("facts") or [])[-limit:]:
        text = row.get("text") if isinstance(row, dict) else str(row)
        if text:
            out.append(f"• {text}")
    return out


def forget_life_line(display):
    text = re.sub(r"^[♪▶📞•]\s*", "", (display or "").strip())
    text = re.sub(r"\s*\(\d+\)\s*$", "", text).strip()
    key = _title_key(text)
    if not key:
        return
    load_memory, save_memory = _memory_io()
    mem = load_memory()
    life = _life_bucket(mem)
    life["facts"] = [
        r for r in (life.get("facts") or [])
        if _title_key((r.get("text") if isinstance(r, dict) else str(r)) or "") != key
        and _title_key((r.get("text") if isinstance(r, dict) else str(r)) or "") != _title_key(f"Likes {text}")
    ]
    save_memory(mem)


def clear_life():
    load_memory, save_memory = _memory_io()
    mem = load_memory()
    mem["life"] = {"facts": []}
    save_memory(mem)


def life_prompt_lines(memory=None):
    if memory is None:
        load_memory, _ = _memory_io()
        memory = load_memory()
    life = memory.get("life") if isinstance(memory.get("life"), dict) else {}
    facts = [
        (r.get("text") if isinstance(r, dict) else str(r))
        for r in (life.get("facts") or [])[-8:]
    ]
    facts = [f for f in facts if f]
    if not facts:
        return []
    return [
        "Personal facts the user told you (not media). Use quietly — don't recite unless asked.",
        *(f"- {f}" for f in facts),
    ]


def startup_recall():
    """Do not mention songs or videos. Facts live in the prompt."""
    return ""


_NOT_USER_NAMES = {
    "aemyos", "davi", "dayi", "dayı", "assistant", "user", "me", "you",
}


def _looks_like_person_name(value):
    n = (value or "").strip().rstrip(".")
    if not n or len(n) > 40:
        return False
    parts = n.split()
    if not (1 <= len(parts) <= 3):
        return False
    if _fold(n) in _NOT_USER_NAMES:
        return False
    return True


def _name_from_fact(text):
    raw = (text or "").strip()
    m = re.match(r"^name:\s*(.+)$", raw, re.IGNORECASE)
    if not m:
        return None
    name = m.group(1).strip()
    return name if _looks_like_person_name(name) else None


def known_user_name(persist=True):
    """Person's name from profile, facts, or what they said in history."""
    load_memory, _ = _memory_io()
    mem = load_memory()
    user = mem.get("user") if isinstance(mem.get("user"), dict) else {}
    name = str(user.get("name") or "").strip()
    if _looks_like_person_name(name):
        return name

    life = mem.get("life") if isinstance(mem.get("life"), dict) else {}
    for row in reversed(list(life.get("facts") or [])):
        text = row.get("text") if isinstance(row, dict) else str(row)
        found = _name_from_fact(text)
        if found:
            if persist:
                set_profile("name", found)
            return found

    for row in reversed(list(mem.get("history") or [])):
        if not isinstance(row, dict):
            continue
        if str(row.get("role") or "") not in ("you", "user"):
            continue
        found = match_set_name(row.get("text") or "")
        if found and _looks_like_person_name(found):
            if persist:
                set_profile("name", found)
            return found
    return ""


def life_briefing():
    load_memory, _ = _memory_io()
    mem = load_memory()
    u = mem.get("user") or {}
    life = mem.get("life") if isinstance(mem.get("life"), dict) else {}
    bits = []
    if u.get("name"):
        bits.append(f"name={u['name']}")
    n = len(life.get("facts") or [])
    if n:
        bits.append(f"facts={n}")
    return " · ".join(bits)


def _is_media_note(text):
    t = (text or "").strip()
    return t.startswith("▶ ") or t.startswith("📞 ")


def strip_media_from_memory():
    """Drop song/video/meeting dumps. Keep profile + facts the user said."""
    load_memory, save_memory = _memory_io()
    mem = load_memory()
    changed = False
    notes = []
    for row in (mem.get("notes") or []):
        text = row.get("text") if isinstance(row, dict) else str(row)
        if _is_media_note(text):
            changed = True
            continue
        notes.append(row)
    if len(notes) != len(mem.get("notes") or []):
        mem["notes"] = notes
        changed = True
    life = mem.get("life") if isinstance(mem.get("life"), dict) else {}
    facts = list(life.get("facts") or []) if isinstance(life, dict) else []
    if life.get("music") or life.get("video") or life.get("meetings") or "music" in life or "video" in life:
        changed = True
    mem["life"] = {"facts": facts[-MAX_FACTS:]}
    if changed:
        save_memory(mem)
        print("[LIFE] stripped music/video/meeting dumps")
    return changed


# ── User profile ─────────────────────────────────────────────────

_PROFILE_FIELDS = ("name", "role", "location")


def set_profile(field, value):
    field = (field or "").strip().lower()
    value = (value or "").strip().rstrip(".")
    if field not in _PROFILE_FIELDS or not value:
        return None
    load_memory, save_memory = _memory_io()
    mem = load_memory()
    user = dict(mem.get("user") or {})
    user[field] = value[:80]
    mem["user"] = user
    save_memory(mem)
    return value


def get_profile():
    load_memory, _ = _memory_io()
    return dict(load_memory().get("user") or {})


# ── Routines ─────────────────────────────────────────────────────

def save_routine(name, steps):
    name = (name or "").strip().rstrip(".")
    if isinstance(steps, str):
        steps = [steps]
    steps = [str(s).strip() for s in (steps or []) if str(s).strip()]
    if not name or not steps:
        return None
    load_memory, save_memory = _memory_io()
    mem = load_memory()
    routines = [r for r in (mem.get("routines") or [])
                if _fold(r.get("name", "")) != _fold(name)]
    routines.append({
        "name": name[:60],
        "steps": steps[:MAX_ROUTINE_STEPS],
        "created": datetime.now().strftime("%Y-%m-%d"),
    })
    mem["routines"] = routines[-MAX_ROUTINES:]
    save_memory(mem)
    return name


def list_routines():
    load_memory, _ = _memory_io()
    out = []
    for row in (load_memory().get("routines") or []):
        if isinstance(row, dict) and row.get("name") and row.get("steps"):
            out.append({"name": str(row["name"]), "steps": [str(s) for s in row["steps"]]})
    return out


def find_routine(query):
    """Exact fold match first, then containment, so 'run my morning routine'
    still finds a routine saved as 'morning'."""
    q = _fold(query)
    if not q:
        return None
    rows = list_routines()
    for row in rows:
        if _fold(row["name"]) == q:
            return row
    best = None
    for row in rows:
        folded = _fold(row["name"])
        if folded and (folded in q or q in folded):
            if best is None or len(folded) > len(_fold(best["name"])):
                best = row
    return best


def delete_routine(name):
    load_memory, save_memory = _memory_io()
    mem = load_memory()
    mem["routines"] = [r for r in (mem.get("routines") or [])
                       if _fold(r.get("name", "")) != _fold(name)]
    save_memory(mem)


# ── Conversation history ─────────────────────────────────────────

MAX_HISTORY = 60


def add_history(role, text):
    """Record one side of a turn. Kept short and capped so the file stays
    readable and the settings viewer stays fast."""
    text = (text or "").strip()
    if not text or role not in ("you", "davi"):
        return
    try:
        load_memory, save_memory = _memory_io()
        mem = load_memory()
        rows = list(mem.get("history") or [])
        rows.append({
            "role": role,
            "text": text[:300],
            "time": datetime.now().strftime("%m-%d %H:%M"),
        })
        mem["history"] = rows[-MAX_HISTORY:]
        save_memory(mem)
    except Exception as exc:
        print(f"[HISTORY] {exc}")


def list_history(limit=40):
    load_memory, _ = _memory_io()
    rows = list((load_memory().get("history") or []))[-limit:]
    return [
        {"role": str(r.get("role") or "you"), "text": str(r.get("text") or ""),
         "time": str(r.get("time") or "")}
        for r in rows if isinstance(r, dict) and str(r.get("text") or "").strip()
    ]


def clear_history():
    load_memory, save_memory = _memory_io()
    mem = load_memory()
    mem["history"] = []
    save_memory(mem)


# ── Voice matching ───────────────────────────────────────────────

_NOTE_PREFIXES = [
    r"(?:take|make|write|add|save)\s+(?:a\s+)?note[:\s]+(.+)",
    r"note\s+(?:this|that)?[:\s]+(.+)",
    r"not\s+(?:al|et|olarak\s+kaydet)[:\s]+(.+)",
    r"(?:bir\s+)?not\s+al[:\s]+(.+)",
    r"(?:sunu|bunu)\s+not\s+al[:\s]*(.+)",
    r"(?:kaydet|yaz)\s+not[:\s]+(.+)",
]

_LIST_NOTES = {
    "my notes", "what are my notes", "read my notes", "show my notes",
    "list my notes", "read notes", "show notes", "notes",
    "notlarim", "notlarim ne", "notlarimi oku", "notlari oku",
    "notlarimi goster", "notlari goster", "notlar",
}

_NAME_PATTERNS = [
    r"(?:my name is|i am called|call me)\s+(.+)",
    r"(?:benim\s+)?ad(?:i?m|imi)\s+(.+?)(?:\s*dir)?$",
    r"bana\s+(.+?)\s+(?:de|diye\s+hitap\s+et|desene)$",
]

_LIKE_PATTERNS = [
    r"i (?:like|love|enjoy|prefer)\s+(.+)$",
    r"ben\s+(.+?)\s+seviyorum",
    r"(?:en\s+sevdigim|favorim)\s+(.+)$",
]

_LIVE_PATTERNS = [
    r"i (?:live|am based) in\s+(.+)$",
    r"(.+?)\s*(?:de|da)\s+yasiyorum",
]

_ROLE_PATTERNS = [
    r"i work (?:as|at)\s+(.+)$",
    r"ben\s+(.+?)\s+(?:olarak\s+)?calisiyorum",
]

_RUN_ROUTINE = [
    r"(?:run|start|do|execute)\s+(?:my\s+)?(.+?)\s+routine",
    r"(?:run|start|do)\s+routine\s+(.+)",
    r"(.+?)\s+rutinimi?\s*(?:calistir|baslat|yap)",
    r"rutin(?:i|imi)?\s+(?:calistir|baslat)\s+(.+)",
]


def match_add_note(text):
    folded = _fold(text)
    for pattern in _NOTE_PREFIXES:
        m = re.search(pattern, folded)
        if m:
            note = m.group(1).strip()
            if note:
                # Fold strips punctuation and casing, so recover the original
                # wording when we can still line it up with the raw utterance.
                return _recover_original(text, note)
    return None


def match_list_notes(text):
    return _fold(text) in _LIST_NOTES


def match_set_name(text):
    folded = _fold(text)
    for pattern in _NAME_PATTERNS:
        m = re.search(pattern, folded)
        if m:
            name = m.group(1).strip()
            # Guard against "my name is" swallowing a whole sentence.
            if name and len(name.split()) <= 4:
                return _recover_original(text, name).title()
    return None


def _short_capture(text, patterns, max_words=6):
    folded = _fold(text)
    for pattern in patterns:
        m = re.search(pattern, folded)
        if not m:
            continue
        value = m.group(1).strip()
        if value and len(value.split()) <= max_words:
            return _recover_original(text, value)
    return None


def match_like(text):
    return _short_capture(text, _LIKE_PATTERNS)


def match_location(text):
    return _short_capture(text, _LIVE_PATTERNS, max_words=5)


def match_role(text):
    return _short_capture(text, _ROLE_PATTERNS, max_words=5)


def match_run_routine(text):
    folded = _fold(text)
    for pattern in _RUN_ROUTINE:
        m = re.search(pattern, folded)
        if m:
            name = m.group(1).strip()
            if name:
                return name
    return None


def _recover_original(raw, folded_fragment):
    """Map a folded match back onto the raw text so notes keep their casing,
    punctuation and Turkish characters.

    Word counts can differ between the two (folding splits "10.0.0.4" into four
    words), so compare folded forms of raw slices rather than counting words.
    Utterances are short, so scanning every slice is cheap.
    """
    if not folded_fragment:
        return folded_fragment
    words = (raw or "").split()
    for start in range(len(words)):
        for end in range(len(words), start, -1):
            candidate = " ".join(words[start:end]).strip().strip(",").rstrip(".")
            if candidate and _fold(candidate) == folded_fragment:
                return candidate
    return folded_fragment
