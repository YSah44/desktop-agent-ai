import re
import pathlib

APP = pathlib.Path(r"C:\Users\Kabexnuf\desktop-agent")
SITE = pathlib.Path(r"C:\Users\Kabexnuf\davi-site")


def sub_name(s):
    s = re.sub(r"DAVI(?!_|EXTRA)", "Aemyos", s)
    s = s.replace("Dayi", "Aemyos")
    return s


app_files = [
    APP / "services" / "i18n.py",
    APP / "prompts" / "default.md",
    APP / "services" / "tray.py",
    APP / "services" / "smart_features.py",
    APP / "services" / "execute_funcs.py",
    APP / "services" / "watchers.py",
    APP / "services" / "safety.py",
    APP / "services" / "windows_ops.py",
    APP / "services" / "busy_audio.py",
    APP / "chrome-extension" / "background.js",
    APP / "chrome-extension" / "install.html",
    APP / "chrome-extension" / "popup.html",
    APP / "chrome-extension" / "manifest.json",
    APP / "chrome-extension" / "popup.js",
    APP / "config.py",
    APP / "main.py",
]

for p in app_files:
    if not p.exists():
        print("skip missing", p)
        continue
    t = p.read_text(encoding="utf-8")
    n = sub_name(t)
    if n != t:
        p.write_text(n, encoding="utf-8")
        print("ok", p.relative_to(APP))

site_files = list(SITE.glob("*.html")) + list((SITE / "js").glob("*.js"))
site_files += [SITE / "README.md", SITE / "sitemap.xml", SITE / "robots.txt"]
for p in site_files:
    t = p.read_text(encoding="utf-8")
    n = sub_name(t)
    n = n.replace("davi.app", "aemyos.app")
    n = n.replace("hello@davi.app", "hello@aemyos.app")
    if n != t:
        p.write_text(n, encoding="utf-8")
        print("ok", p.name)

print("done")
