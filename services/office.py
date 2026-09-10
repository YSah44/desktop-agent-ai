"""Microsoft Office through COM automation: Word dictation, Excel rows, Outlook mail,
inbox and calendar. Far more reliable than clicking the ribbon."""
import re
from datetime import datetime, timedelta


def _com(fn):
    def wrapped(*a, **kw):
        import pythoncom
        pythoncom.CoInitialize()
        try:
            return fn(*a, **kw)
        except Exception as e:
            return {"success": False, "message": f"{fn.__name__}: {_friendly(e)}"}
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
    wrapped.__name__ = fn.__name__
    return wrapped


def _friendly(e):
    s = str(e)
    if "not connected" in s.lower():
        return "Outlook has no mail account set up on this PC (it says 'You are not connected')"
    if "Server execution failed" in s:
        return "the Office app is still starting or showing a dialog; try again in a few seconds"
    if "Operation aborted" in s:
        return "Outlook refused the operation (not signed in, or a dialog is open)"
    if "is not open" in s:
        return s
    return s[:200]


def _app(prog_id, create=True):
    import win32com.client
    try:
        return win32com.client.GetActiveObject(prog_id), True
    except Exception:
        if not create:
            raise RuntimeError(f"{prog_id.split('.')[0]} is not open")
        app = win32com.client.Dispatch(prog_id)
        return app, False


# ── Word ─────────────────────────────────────────────────────────

@_com
def word_type(text, new_document=False):
    text = (text or "").strip()
    if not text:
        return {"success": False, "message": "Nothing to type"}
    word, _ = _app("Word.Application")
    word.Visible = True
    if new_document or word.Documents.Count == 0:
        word.Documents.Add()
    word.Selection.TypeText(text if text.endswith((" ", "\n")) else text + " ")
    try:
        word.Activate()
    except Exception:
        pass
    return {"success": True, "message": f"Typed into Word: {text[:80]}"}


@_com
def word_save(path=None):
    word, _ = _app("Word.Application", create=False)
    doc = word.ActiveDocument
    if path:
        doc.SaveAs2(path)
    else:
        doc.Save()
    return {"success": True, "message": f"Saved {doc.FullName}"}


# ── Excel ────────────────────────────────────────────────────────

def _split_values(values):
    if isinstance(values, (list, tuple)):
        return [str(v).strip() for v in values]
    raw = str(values or "")
    parts = re.split(r"\s*[;,|]\s*|\t", raw)
    return [p.strip() for p in parts if p.strip()]


def _coerce(v):
    try:
        if re.fullmatch(r"-?\d+", v):
            return int(v)
        if re.fullmatch(r"-?\d+[.,]\d+", v):
            return float(v.replace(",", "."))
    except Exception:
        pass
    return v


@_com
def excel_add_row(values, sheet=None):
    vals = _split_values(values)
    if not vals:
        return {"success": False, "message": "No values"}
    excel, _ = _app("Excel.Application")
    excel.Visible = True
    if excel.Workbooks.Count == 0:
        excel.Workbooks.Add()
    ws = excel.ActiveSheet if not sheet else excel.ActiveWorkbook.Worksheets(sheet)
    used = ws.UsedRange
    last = used.Row + used.Rows.Count - 1
    first_empty = 1 if (last == 1 and not ws.Cells(1, 1).Value) else last + 1
    for i, v in enumerate(vals, start=1):
        ws.Cells(first_empty, i).Value = _coerce(v)
    return {"success": True, "message": f"Excel row {first_empty}: {', '.join(vals)}", "row": first_empty}


@_com
def excel_set_cell(cell, value, sheet=None):
    excel, _ = _app("Excel.Application", create=False)
    ws = excel.ActiveSheet if not sheet else excel.ActiveWorkbook.Worksheets(sheet)
    ws.Range(cell).Value = _coerce(str(value))
    return {"success": True, "message": f"{cell} = {value}"}


# ── Outlook ──────────────────────────────────────────────────────

@_com
def outlook_mail(to, subject="", body="", send=False, cc=""):
    outlook, _ = _app("Outlook.Application")
    mail = outlook.CreateItem(0)
    mail.To = to
    if cc:
        mail.CC = cc
    mail.Subject = subject or ""
    mail.Body = body or ""
    if send:
        mail.Send()
        return {"success": True, "message": f"Sent mail to {to}: {subject}"}
    mail.Display(False)
    return {"success": True, "message": f"Mail to {to} opened for review (not sent): {subject}"}


@_com
def outlook_inbox(limit=5, unread_only=False):
    outlook, _ = _app("Outlook.Application")
    ns = outlook.GetNamespace("MAPI")
    inbox = ns.GetDefaultFolder(6)
    items = inbox.Items
    items.Sort("[ReceivedTime]", True)
    if unread_only:
        items = items.Restrict("[Unread] = True")
    out = []
    n = 0
    for item in items:
        try:
            when = item.ReceivedTime
            out.append(f"{str(when)[:16]} · {item.SenderName}: {item.Subject}")
        except Exception:
            continue
        n += 1
        if n >= int(limit or 5):
            break
    return {"success": True, "message": ("\n".join(out) if out else "Inbox is empty"), "count": n}


def _parse_when(text):
    """'tomorrow 15:00', '2026-09-12 09:30', 'today 4pm' → datetime."""
    t = (text or "").strip().lower()
    now = datetime.now()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})[ t](\d{1,2})[:.](\d{2})", t)
    if m:
        return datetime(int(m[1]), int(m[2]), int(m[3]), int(m[4]), int(m[5]))
    day = now
    if "tomorrow" in t or "yarin" in t or "yarın" in t:
        day = now + timedelta(days=1)
    m = re.search(r"(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?", t)
    if not m:
        return None
    hour = int(m[1])
    minute = int(m[2] or 0)
    if m[3] == "pm" and hour < 12:
        hour += 12
    if m[3] == "am" and hour == 12:
        hour = 0
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


@_com
def outlook_event(subject, when, duration_min=60, location=""):
    start = _parse_when(when) if isinstance(when, str) else when
    if not start:
        return {"success": False, "message": f"Could not understand the time '{when}'"}
    outlook, _ = _app("Outlook.Application")
    appt = outlook.CreateItem(1)
    appt.Subject = subject
    appt.Start = start
    appt.Duration = int(duration_min or 60)
    if location:
        appt.Location = location
    appt.ReminderMinutesBeforeStart = 10
    appt.Save()
    return {"success": True, "message": f"Calendar: {subject} at {start.strftime('%Y-%m-%d %H:%M')}"}


# ── Fast-path parsing ───────────────────────────────────────────

_WORD = [
    re.compile(r"^(?:type|write|dictate)\s+(?:this\s+)?(?:in|into|to)\s+word\s*:\s*(?P<text>.+)$", re.I),
    re.compile(r"^word\s*:\s*(?P<text>.+)$", re.I),
    re.compile(r"^word['’]?[ea]\s+(?:yaz|ekle)\s*:\s*(?P<text>.+)$", re.I),
]
_EXCEL = [
    re.compile(r"^(?:add|insert)\s+(?:a\s+)?row\s+(?:to|in)\s+excel\s*:\s*(?P<vals>.+)$", re.I),
    re.compile(r"^excel\s*:\s*(?P<vals>.+)$", re.I),
    re.compile(r"^excel['’]?[ea]\s+(?:satir|satır)\s+ekle\s*:\s*(?P<vals>.+)$", re.I),
]
_INBOX = re.compile(
    r"^(?:read|check|show)\s+(?:my\s+)?(?:unread\s+|new\s+|latest\s+)?(?:inbox|e-?mails?|mails?)\b"
    r"|^(?:gelen kutusu\w*|(?:okunmamis\s+)?mail?lerimi?|e-?postalarimi?)\s*(?:oku|goster|bak)", re.I)


def parse_request(text):
    raw = (text or "").strip()
    folded = raw.replace("İ", "i").replace("ı", "i").replace("ş", "s").replace("ç", "c").replace("ğ", "g").replace("ö", "o").replace("ü", "u")
    for pat in _WORD:
        m = pat.match(folded)
        if m:
            body = raw.split(":", 1)[1].strip() if ":" in raw else m.group("text")
            return {"kind": "word", "text": body}
    for pat in _EXCEL:
        m = pat.match(folded)
        if m:
            body = raw.split(":", 1)[1].strip() if ":" in raw else m.group("vals")
            return {"kind": "excel", "values": body}
    if _INBOX.match(folded):
        return {"kind": "inbox", "unread": "unread" in folded or "okunmamis" in folded}
    return None
