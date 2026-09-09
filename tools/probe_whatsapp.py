"""Dev probe: list the UIA controls WhatsApp Desktop exposes (search box, message box, send)."""
import sys
import time

sys.path.insert(0, ".")
from services import win_uia, windows_ops  # noqa: E402

r = windows_ops.focus_window("WhatsApp")
print("focus:", r)
time.sleep(1.0)
match = windows_ops.find_hwnd("WhatsApp", skip_davi=True)
hwnd = match["hwnd"] if match else None
print("hwnd:", hwnd, match and match.get("title"))

for ctype in ("Edit", "Button", "ListItem", "Document"):
    hits = win_uia.find_controls(control_type=ctype, hwnd=hwnd, limit=12)
    print(f"--- {ctype}: {len(hits)}")
    for h in hits[:12]:
        print("  ", repr(h.get("name", ""))[:60], "| auto_id:", h.get("automation_id", ""), "| at", h.get("x"), h.get("y"))
