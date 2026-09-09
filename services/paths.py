"""Where files live. Source checkout: everything in the project folder.
Packaged exe: read-only resources next to the exe, user data in %APPDATA%\\Aemyos."""
import os
import sys

FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
    RES_DIR = getattr(sys, "_MEIPASS", APP_DIR)
    DATA_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Aemyos")
else:
    APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    RES_DIR = APP_DIR
    DATA_DIR = APP_DIR

os.makedirs(DATA_DIR, exist_ok=True)


def res_path(*parts):
    return os.path.join(RES_DIR, *parts)


def data_path(*parts):
    return os.path.join(DATA_DIR, *parts)
