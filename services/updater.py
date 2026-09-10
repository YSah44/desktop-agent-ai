"""In-app updates from GitHub releases: check, download the signed installer,
verify its SHA256 against SHA256SUMS.txt, run it silently (Inno closes and relaunches us)."""
import hashlib
import os
import re
import subprocess
import tempfile
import threading
import time

import requests

REPO = "YSah44/desktop-agent-ai"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET = "Aemyos-Setup.exe"
SUMS = "SHA256SUMS.txt"
CHECK_EVERY_SEC = 6 * 3600

_latest = None
_listeners = []


def parse_version(text):
    nums = re.findall(r"\d+", str(text or ""))
    return tuple(int(n) for n in nums[:3]) or (0,)


def is_dev_build():
    try:
        from config import DAVI_VERSION, CHANNEL
        return "dev" in str(DAVI_VERSION).lower() or bool(CHANNEL)
    except Exception:
        return False


def current_version():
    try:
        from config import DAVI_VERSION
        return parse_version(DAVI_VERSION)
    except Exception:
        return (0,)


def check(timeout=12):
    """Return {version, tag, url, sums_url, notes} when a newer release exists, else None."""
    global _latest
    r = requests.get(API, timeout=timeout, headers={"Accept": "application/vnd.github+json"})
    r.raise_for_status()
    data = r.json()
    tag = str(data.get("tag_name") or "")
    remote = parse_version(tag)
    url = sums_url = None
    for a in data.get("assets") or []:
        name = a.get("name") or ""
        if name == ASSET:
            url = a.get("browser_download_url")
        elif name == SUMS:
            sums_url = a.get("browser_download_url")
    if not url or remote <= current_version():
        _latest = None
        return None
    _latest = {
        "version": ".".join(str(n) for n in remote),
        "tag": tag,
        "url": url,
        "sums_url": sums_url,
        "notes": str(data.get("body") or "")[:2000],
    }
    return _latest


def latest():
    return _latest


def _expected_sha(sums_url):
    if not sums_url:
        return None
    try:
        txt = requests.get(sums_url, timeout=12).text
    except Exception:
        return None
    for line in txt.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].strip() == ASSET:
            return parts[0].strip().lower()
    return None


def download(info, progress=None):
    """Download the installer to %TEMP%, verify SHA256 when SHA256SUMS.txt is published."""
    dest = os.path.join(tempfile.gettempdir(), "Aemyos-Update.exe")
    with requests.get(info["url"], stream=True, timeout=30) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        h = hashlib.sha256()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if not chunk:
                    continue
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress and total:
                    progress(done / total)
    expected = _expected_sha(info.get("sums_url"))
    if expected and h.hexdigest().lower() != expected:
        os.remove(dest)
        raise ValueError("SHA256 mismatch — download discarded")
    return dest


def install(path):
    """Run the signed Inno installer silently; it closes Aemyos, replaces files and relaunches."""
    subprocess.Popen([path, "/SILENT", "/CLOSEAPPLICATIONS", "/NORESTART"], close_fds=True)


def add_listener(fn):
    """fn(info) is called from the checker thread whenever a newer release is seen."""
    _listeners.append(fn)


def start_background_checks(initial_delay=25):
    if is_dev_build():
        print("[UPDATE] dev build — automatic update checks off")
        return

    def _loop():
        time.sleep(initial_delay)
        while True:
            try:
                info = check()
                if info:
                    print(f"[UPDATE] {info['version']} available")
                    for fn in list(_listeners):
                        try:
                            fn(info)
                        except Exception:
                            pass
            except Exception as e:
                print(f"[UPDATE] check failed: {e}")
            time.sleep(CHECK_EVERY_SEC)

    threading.Thread(target=_loop, name="aemyos-updater", daemon=True).start()
