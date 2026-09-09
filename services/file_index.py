"""Local file index for "open the PDF I downloaded last week" style requests.
Scans the user's folders in a background thread (no Windows Search dependency),
keeps name/path/mtime/size in memory, refreshes every few minutes."""
import os
import re
import threading
import time

_ROOTS = ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music", "OneDrive")
_SKIP_DIRS = {
    "node_modules", ".git", "venv", ".venv", "__pycache__", "appdata", "$recycle.bin",
    "site-packages", ".cache", "cache", "build", "dist", ".vs", ".idea",
}
_MAX_DEPTH = 6
_REFRESH_SEC = 300

KINDS = {
    "pdf": {".pdf"},
    "doc": {".doc", ".docx", ".txt", ".rtf", ".odt", ".md"},
    "sheet": {".xls", ".xlsx", ".csv", ".ods"},
    "slides": {".ppt", ".pptx", ".odp"},
    "image": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp", ".svg"},
    "video": {".mp4", ".mkv", ".mov", ".avi", ".webm"},
    "audio": {".mp3", ".wav", ".m4a", ".flac", ".ogg"},
    "zip": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "exe": {".exe", ".msi"},
    "code": {".py", ".js", ".ts", ".html", ".css", ".json", ".c", ".cpp", ".java", ".go", ".rs"},
}
_KIND_WORDS = {
    "pdf": "pdf",
    "photo": "image", "photos": "image", "picture": "image", "pictures": "image", "image": "image",
    "images": "image", "screenshot": "image", "screenshots": "image", "resim": "image", "resmi": "image",
    "fotograf": "image", "fotografi": "image", "foto": "image", "fotoyu": "image", "ekran goruntusu": "image",
    "video": "video", "videos": "video", "videoyu": "video", "film": "video",
    "song": "audio", "songs": "audio", "music": "audio", "mp3": "audio", "sarki": "audio", "sarkiyi": "audio",
    "muzik": "audio", "muzigi": "audio", "ses": "audio",
    "zip": "zip", "archive": "zip", "arsiv": "zip",
    "document": "doc", "documents": "doc", "doc": "doc", "word": "doc", "belge": "doc", "belgeyi": "doc",
    "dokuman": "doc", "dokumani": "doc", "text": "doc", "txt": "doc",
    "excel": "sheet", "spreadsheet": "sheet", "sheet": "sheet", "tablo": "sheet", "tabloyu": "sheet", "csv": "sheet",
    "powerpoint": "slides", "presentation": "slides", "slides": "slides", "sunum": "slides", "sunumu": "slides",
    "installer": "exe", "setup": "exe", "exe": "exe", "program": "exe", "programi": "exe",
}
_FOLDER_WORDS = {
    "download": "Downloads", "downloads": "Downloads", "downloaded": "Downloads", "indirilen": "Downloads",
    "indirilenler": "Downloads", "indirdigim": "Downloads", "indirdiklerim": "Downloads",
    "desktop": "Desktop", "masaustu": "Desktop", "masaustundeki": "Desktop",
    "document": "Documents", "documents": "Documents", "belgeler": "Documents", "belgelerdeki": "Documents",
    "picture": "Pictures", "pictures": "Pictures", "resimler": "Pictures", "resimlerdeki": "Pictures",
    "video": "Videos", "videos": "Videos", "videolar": "Videos",
    "music": "Music", "muzik": "Music", "muzikler": "Music",
}
_TIME_WORDS = (
    (r"\b(today|bugun)\b", 1),
    (r"\b(yesterday|dun)\b", 2),
    (r"\b(this week|bu hafta)\b", 7),
    (r"\b(last week|gecen hafta|past week)\b", 14),
    (r"\b(this month|bu ay)\b", 31),
    (r"\b(last month|gecen ay)\b", 62),
    (r"\b(recently|lately|son zamanlarda|yakinda)\b", 14),
)
_RECENT_WORDS = re.compile(r"\b(last|latest|recent|newest|most recent|son|en son|en yeni|sonuncu)\b")
_STOP = {
    "open", "show", "find", "the", "my", "a", "an", "i", "file", "files", "that", "which", "one", "please",
    "ac", "goster", "bul", "dosya", "dosyayi", "dosyalari", "bir", "su", "bu", "o", "lutfen", "from", "in", "on",
    "of", "me", "for", "and", "with", "to", "ile", "ve", "en", "week", "month", "days", "hafta", "ay", "gun",
    "gecen", "last", "latest", "recent", "newest", "most", "son", "yeni", "sonuncu", "today", "bugun",
    "yesterday", "dun", "this", "recently", "lately", "downloaded", "indirdigim", "downloads", "download",
}

_lock = threading.Lock()
_entries = []
_built_at = 0.0
_building = False


def _roots():
    home = os.path.expanduser("~")
    out = []
    for name in _ROOTS:
        p = os.path.join(home, name)
        if os.path.isdir(p):
            out.append(p)
    return out


def _scan(root, depth=0, out=None):
    if out is None:
        out = []
    try:
        with os.scandir(root) as it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        if depth < _MAX_DEPTH and e.name.lower() not in _SKIP_DIRS and not e.name.startswith("."):
                            _scan(e.path, depth + 1, out)
                    elif e.is_file(follow_symlinks=False):
                        st = e.stat(follow_symlinks=False)
                        name = e.name
                        out.append((name.lower(), e.path, st.st_mtime, st.st_size, os.path.splitext(name)[1].lower()))
                except (OSError, PermissionError):
                    continue
    except (OSError, PermissionError):
        pass
    return out


def rebuild():
    global _entries, _built_at, _building
    if _building:
        return
    _building = True
    try:
        found = []
        for r in _roots():
            _scan(r, 0, found)
        with _lock:
            _entries = found
            _built_at = time.time()
        print(f"[FILES] indexed {len(found)} files")
    finally:
        _building = False


def _refresher():
    rebuild()
    while True:
        time.sleep(_REFRESH_SEC)
        try:
            rebuild()
        except Exception:
            pass


def start_indexer():
    threading.Thread(target=_refresher, name="aemyos-file-index", daemon=True).start()


def fold(text):
    table = str.maketrans({"ı": "i", "İ": "i", "ğ": "g", "Ğ": "g", "ü": "u", "Ü": "u", "ş": "s", "Ş": "s",
                           "ö": "o", "Ö": "o", "ç": "c", "Ç": "c"})
    t = (text or "").lower().translate(table)
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s.]+", " ", t)).strip()


def parse_request(text):
    """Pull kind / days / folder / free words out of a natural request.
    Returns None unless the sentence clearly asks for a recent or dated file."""
    n = fold(text)
    if not n:
        return None
    days = None
    for pat, d in _TIME_WORDS:
        if re.search(pat, n):
            days = d
            break
    recent = bool(_RECENT_WORDS.search(n))
    if days is None and not recent:
        return None
    # English puts the verb first, Turkish last ("... pdf'i aç").
    if not re.search(r"\b(open|show|find|play|ac|goster|bul|oynat)\b", n):
        return None
    kind = None
    folder = None
    words = []
    for w in n.split():
        if w in _KIND_WORDS and kind is None:
            kind = _KIND_WORDS[w]
        elif w in _FOLDER_WORDS and folder is None:
            folder = _FOLDER_WORDS[w]
        elif w not in _STOP and w not in _KIND_WORDS and w not in _FOLDER_WORDS:
            words.append(w)
    return {"kind": kind, "days": days, "folder": folder, "query": " ".join(words)}


def search(query="", kind=None, days=None, folder=None, limit=8):
    q_words = [w for w in fold(query).split() if w]
    exts = KINDS.get(kind or "", None)
    cutoff = time.time() - days * 86400 if days else None
    home = os.path.expanduser("~").lower()
    folder_prefix = os.path.join(home, folder).lower() if folder else None
    with _lock:
        rows = list(_entries)
    hits = []
    for name, path, mtime, size, ext in rows:
        if exts and ext not in exts:
            continue
        if cutoff and mtime < cutoff:
            continue
        if folder_prefix and not path.lower().startswith(folder_prefix):
            continue
        score = 0
        if q_words:
            if not all(w in name for w in q_words):
                continue
            score = sum(len(w) for w in q_words)
        hits.append((score, mtime, name, path, size))
    hits.sort(key=lambda h: (h[0], h[1]), reverse=True)
    return [{"name": os.path.basename(p), "path": p, "mtime": m, "size": s} for _, m, _, p, s in hits[:limit]]


def describe(results):
    if not results:
        return "No matching files."
    lines = []
    for r in results:
        age = time.time() - r["mtime"]
        when = "today" if age < 86400 else f"{int(age // 86400)}d ago"
        lines.append(f"{r['name']} — {r['path']} ({when}, {r['size'] // 1024} KB)")
    return "\n".join(lines)


def open_path(path):
    path = (path or "").strip().strip('"')
    if not path or not os.path.exists(path):
        return {"success": False, "message": f"Not found: {path}"}
    try:
        os.startfile(path)
        return {"success": True, "message": f"Opened {os.path.basename(path)}", "name": os.path.basename(path), "path": path}
    except Exception as e:
        return {"success": False, "message": f"Open failed: {e}"}


def open_recent(kind=None, days=None, folder=None, query=""):
    results = search(query=query, kind=kind, days=days, folder=folder, limit=1)
    if not results:
        return {"success": False, "message": "No matching file"}
    r = open_path(results[0]["path"])
    r["candidates"] = search(query=query, kind=kind, days=days, folder=folder, limit=5)
    return r
