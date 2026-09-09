# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: venv\Scripts\python.exe -m PyInstaller aemyos.spec --noconfirm --clean
import os
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None


def asset_files():
    # assets/face_real.jpg is the owner's own photo (gitignored) — never ship it.
    out = []
    for root, _, files in os.walk("assets"):
        for f in files:
            if f.lower().startswith("face_real"):
                continue
            p = os.path.join(root, f)
            out.append((p, root))
    return out


datas = asset_files() + [
    ("prompts", "prompts"),
    ("memory.template.json", "."),
    (".env.example", "."),
    ("chrome-extension", "chrome-extension"),
]

hiddenimports = [
    "comtypes", "comtypes.client", "comtypes.gen",
    "pystray._win32",
    "pynput.keyboard._win32", "pynput.mouse._win32",
    "edge_tts", "pygame", "sounddevice", "_sounddevice_data",
    "cv2", "websockets", "websockets.server", "websockets.legacy", "websockets.legacy.server",
    "PIL.ImageTk", "PIL._tkinter_finder",
    "screeninfo", "pyperclip", "requests", "numpy",
]
hiddenimports += collect_submodules("services")
hiddenimports += collect_submodules("pywinauto")
hiddenimports += collect_submodules("winsdk")

excludes = [
    "torch", "torchvision", "torchaudio", "whisper", "faster_whisper", "ctranslate2",
    "numba", "llvmlite", "scipy", "matplotlib", "IPython", "jupyter", "notebook",
    "pytest", "sympy", "networkx", "anthropic", "icecream", "tkinter.test",
]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Aemyos",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/icon.ico",
    version="version_info.txt",
    uac_admin=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="Aemyos",
)
