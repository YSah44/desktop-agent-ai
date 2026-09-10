"""Start with Windows (HKCU Run key) and start-hidden preference."""
import os
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Aemyos"
HIDDEN_ENV = "DAVI_START_HIDDEN"


def launch_command(hidden=True):
    flag = " --hidden" if hidden else ""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"{flag}'
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        pyw = exe[:-10] + "pythonw.exe"
        if os.path.isfile(pyw):
            exe = pyw
    main_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
    return f'"{exe}" -u "{main_py}"{flag}'


def is_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, VALUE_NAME)
            return True
    except OSError:
        return False


def set_enabled(on, hidden=True):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, launch_command(hidden))
            else:
                try:
                    winreg.DeleteValue(k, VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError as e:
        print(f"[STARTUP] registry: {e}")
        return False


def starts_hidden():
    return (os.environ.get(HIDDEN_ENV) or "1") == "1"


def set_starts_hidden(on):
    try:
        from config import save_env
        save_env(**{HIDDEN_ENV: "1" if on else "0"})
    except Exception:
        os.environ[HIDDEN_ENV] = "1" if on else "0"
    if is_enabled():
        set_enabled(True, hidden=bool(on))
