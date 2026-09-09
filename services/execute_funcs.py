import json
import os
from datetime import datetime
import sched
import time
import re
import requests as _requests
import pyperclip

from services.paths import data_path as _data_path, res_path as _res_path

MEMORY_PATH = _data_path("memory.json")
LEARNED_MAX = 40
NOTES_MAX = 60
TASKS_MAX = 24
REMINDERS_MAX = 30
ROUTINES_MAX = 30
HISTORY_MAX = 60

def load_memory():
    try:
        with open(MEMORY_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        template = _res_path("memory.template.json")
        try:
            with open(template, 'r', encoding='utf-8') as f:
                data = json.load(f)
            save_memory(data)
            return data
        except Exception:
            return {"user": {}, "preferences": {}, "learned": [], "notes": [], "life": {}, "last_task": None}
    except Exception:
        return {"user": {}, "preferences": {}, "learned": [], "notes": [], "life": {}, "last_task": None}

def save_memory(data):
    try:
        if not isinstance(data, dict):
            data = {}
        learned = data.get("learned")
        if isinstance(learned, list) and len(learned) > LEARNED_MAX:
            data["learned"] = learned[-LEARNED_MAX:]
        notes = data.get("notes")
        if isinstance(notes, list) and len(notes) > NOTES_MAX:
            data["notes"] = notes[-NOTES_MAX:]
        tasks = data.get("tasks")
        if isinstance(tasks, list) and len(tasks) > TASKS_MAX:
            data["tasks"] = tasks[-TASKS_MAX:]
        reminders = data.get("reminders")
        if isinstance(reminders, list) and len(reminders) > REMINDERS_MAX:
            data["reminders"] = reminders[-REMINDERS_MAX:]
        routines = data.get("routines")
        if isinstance(routines, list) and len(routines) > ROUTINES_MAX:
            data["routines"] = routines[-ROUTINES_MAX:]
        history = data.get("history")
        if isinstance(history, list) and len(history) > HISTORY_MAX:
            data["history"] = history[-HISTORY_MAX:]
        life = data.get("life")
        if isinstance(life, dict):
            facts = life.get("facts")
            if isinstance(facts, list) and len(facts) > 20:
                facts = facts[-20:]
            data["life"] = {"facts": facts if isinstance(facts, list) else []}
        with open(MEMORY_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[MEMORY] Save error: {e}")
        return False
from services.cursor import (
    move_cursor_absolute, 
    move_cursor_relative, 
    click_mouse_button, 
    press_key, 
    double_click,
    drag_to,
    mouse_down,
    mouse_up,
    press_hotkey,
    type_text,
    scroll,
    get_cursor_position
)
from services.find_ui import move_mouse_to_ui_element
from services.safety import refuse_if_destructive
from services.desktop_commands import handle as handle_desktop, EXTENDED_COMMANDS
from services.display import ensure_dpi_aware
from services.chrome_router import (
    rewrite_chrome_commands,
    format_tabs_message as _format_tabs_message,
    bridge_find_tab as _bridge_find_tab,
    reuse_or_open_url,
)

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.02
except Exception:
    pyautogui = None

ensure_dpi_aware()

listening = False
_cancel_flag = False
_skip_next_click = False


def set_cancel_flag(val):
    global _cancel_flag
    _cancel_flag = val


def get_cancel_flag():
    return _cancel_flag


def extract_json(text):
    # Remove escape characters for correct JSON parsing
    text = text.replace('\\_', '_')

    json_objects = []
    json_str = ""
    in_json = False
    brace_count = 0

    # List to save start and end positions of JSON insertions
    json_positions = []

    # Iterate through text characters
    for index, char in enumerate(text):
        if char == '{':
            if not in_json:
                start_pos = index  # Save JSON start position
                in_json = True
            brace_count += 1
        if in_json:
            json_str += char
        if char == '}':
            brace_count -= 1
            if brace_count == 0 and in_json:
                try:
                    # Try to convert string to JSON
                    json_obj = json.loads(json_str)
                    json_objects.append(json_obj)

                    # Save positions for removing JSON insertion
                    json_positions.append((start_pos, index + 1))
                except json.JSONDecodeError:
                    pass  # Skip invalid insertions
                in_json = False
                json_str = ""

    # Remove JSON insertions from text based on saved positions
    for start, end in reversed(json_positions):
        text = text[:start] + text[end:]

    return json_objects, text.strip()


def _collapse_url_opens(commands):
    """If Chrome already navigates, drop open_url / extra Chrome launches."""
    cmds = [c for c in (commands or []) if isinstance(c, dict)]
    bridge = {
        str(c.get("command") or "")
        for c in cmds
        if str(c.get("command") or "").startswith("browser_")
    }
    if "browser_navigate" in bridge or "browser_new_tab" in bridge:
        skip_apps = {"chrome", "google chrome", "krom", "youtube", "browser"}
        out = []
        for c in cmds:
            name = str(c.get("command") or "")
            if name == "open_url":
                continue
            if name == "open_app":
                app = str((c.get("params") or {}).get("name") or "").lower().strip()
                if app in skip_apps:
                    continue
            out.append(c)
        return out
    seen_url = False
    out = []
    for c in cmds:
        if str(c.get("command") or "") == "open_url":
            if seen_url:
                continue
            seen_url = True
        out.append(c)
    return out


def process_commands(commands):
    results = []
    try:
        commands = rewrite_chrome_commands(_collapse_url_opens(commands))
        # Process commands in batches for efficiency
        batch_commands = []
        batch_results = []
        
        for command in commands:
            result = {"command": command["command"], "success": True, "message": ""}
            
            try:
                # Group commands that can be batched together
                if command['command'] in ['wait']:
                    # Process any accumulated batch commands first
                    if batch_commands:
                        batch_results = execute_batch_commands(batch_commands)
                        results.extend(batch_results)
                        batch_commands = []
                    
                    # Process the wait command individually
                    seconds = command['params']['seconds']
                    time.sleep(seconds)
                    result["message"] = f"Waited for {seconds} seconds"
                    results.append(result)
                else:
                    # Add command to batch
                    batch_commands.append(command)
                    
                    # If batch size reaches threshold or this is the last command, process the batch
                    if len(batch_commands) >= 3 or command == commands[-1]:
                        batch_results = execute_batch_commands(batch_commands)
                        results.extend(batch_results)
                        batch_commands = []
                        continue
                    
                    # Skip adding this result since it will be added as part of the batch
                    continue
            
            except KeyError as e:
                result["success"] = False
                result["message"] = f"Missing required parameter: {e}"
                results.append(result)
            except Exception as e:
                result["success"] = False
                result["message"] = f"Error executing command: {str(e)}"
                results.append(result)
        
        # Process any remaining batch commands
        if batch_commands:
            batch_results = execute_batch_commands(batch_commands)
            results.extend(batch_results)
    
    except Exception as e:
        print(f"Error processing commands: {e}")
    
    return results


def is_listening():
    global listening
    return listening


def set_listening(value):
    global listening
    listening = value
    return

def execute_batch_commands(commands):
    """Execute a batch of commands efficiently"""
    global listening, _skip_next_click
    results = []

    for command in commands:
        if _cancel_flag:
            results.append({"command": "cancelled", "success": False, "message": "Cancelled by user"})
            break

        result = {"command": command["command"], "success": True, "message": ""}
        try:
            blocked = refuse_if_destructive(command)
            if blocked:
                results.append(blocked)
                continue

            if command['command'] in EXTENDED_COMMANDS:
                extra = handle_desktop(command)
                if extra is not None:
                    result.update(extra)
                    results.append(result)
                    time.sleep(0.15)
                    continue

            if command['command'] == 'move_cursor_absolute':
                move_cursor_absolute(command['params']['x'], command['params']['y'])
                result["message"] = f"Moved cursor to absolute position: {command['params']['x']}, {command['params']['y']}"
            
            elif command['command'] == 'move_cursor_relative':
                move_cursor_relative(command['params']['dx'], command['params']['dy'])
                x, y = get_cursor_position()
                result["message"] = f"Moved cursor by offset: {command['params']['dx']}, {command['params']['dy']}. New position: {x}, {y}"
            
            elif command['command'] == 'mouse_button':
                if _skip_next_click:
                    _skip_next_click = False
                    result["success"] = False
                    result["message"] = "Skipped click: previous element locate failed"
                else:
                    try:
                        clicked = click_mouse_button(command['params']['button'])
                    except Exception:
                        time.sleep(0.2)
                        clicked = click_mouse_button(command['params']['button'])
                    if clicked is False:
                        result["success"] = False
                        result["message"] = "Skipped click: cursor is on the Aemyos overlay"
                    else:
                        result["message"] = f"Clicked {command['params']['button']} mouse button"
            
            elif command['command'] == 'move_cursor_to_element':
                coords = move_mouse_to_ui_element(command['params']['name'])
                if coords:
                    _skip_next_click = False
                    result["message"] = f"Moved cursor to element {command['params']['name']} at {coords}"
                else:
                    _skip_next_click = True
                    result["success"] = False
                    result["message"] = f"Could not find element: {command['params']['name']} (click skipped until a successful locate)"
            
            elif command['command'] == 'double_click':
                if _skip_next_click:
                    _skip_next_click = False
                    result["success"] = False
                    result["message"] = "Skipped double-click: previous element locate failed"
                else:
                    button = command['params'].get('button', 'left')
                    try:
                        clicked = double_click(button)
                    except Exception:
                        time.sleep(0.2)
                        clicked = double_click(button)
                    if clicked is False:
                        result["success"] = False
                        result["message"] = "Skipped double-click: cursor is on the Aemyos overlay"
                    else:
                        result["message"] = f"Double-clicked {button} mouse button"
            
            elif command['command'] == 'drag_to':
                x = command['params']['x']
                y = command['params']['y']
                button = command['params'].get('button', 'left')
                duration = command['params'].get('duration', 0.5)
                dragged = drag_to(x, y, button, duration)
                if dragged is False:
                    result["success"] = False
                    result["message"] = "Skipped drag: target is the Aemyos overlay"
                else:
                    result["message"] = f"Dragged to position: {x}, {y}"
            
            elif command['command'] == 'mouse_down':
                button = command['params'].get('button', 'left')
                held = mouse_down(button)
                if held is False:
                    result["success"] = False
                    result["message"] = "Skipped mouse_down: cursor is on the Aemyos overlay"
                else:
                    result["message"] = f"Pressed and held {button} mouse button"
            
            elif command['command'] == 'mouse_up':
                button = command['params'].get('button', 'left')
                mouse_up(button)
                result["message"] = f"Released {button} mouse button"
            
            elif command['command'] == 'press_key':
                press_key(command['params']['key'])
                result["message"] = f"Pressed key: {command['params']['key']}"
            
            elif command['command'] == 'press_hotkey':
                keys = command['params']['keys']
                keys_lower = [k.lower() for k in keys]
                # Block Alt+F4 — protect against accidentally closing Aemyos or user windows
                if 'alt' in keys_lower and 'f4' in keys_lower:
                    try:
                        import ctypes
                        hwnd = ctypes.windll.user32.GetForegroundWindow()
                        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                        buf = ctypes.create_unicode_buffer(length + 1)
                        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                        low = buf.value.lower()
                        if "aemyos" in low or "davi" in low or "dayi" in low:
                            result["success"] = False
                            result["message"] = "BLOCKED: Cannot close Aemyos window"
                            results.append(result)
                            continue
                    except Exception:
                        pass
                press_hotkey(*keys)
                result["message"] = f"Pressed hotkey combination: {'+'.join(keys)}"
            
            elif command['command'] == 'enter_text':
                text = command['params']['text']
                blocked = ['shutdown', 'restart', 'format ', 'del /f', 'rm -rf', 'rmdir']
                if any(b in text.lower() for b in blocked):
                    result["success"] = False
                    result["message"] = f"BLOCKED dangerous text: {text}"
                    results.append(result)
                    continue
                type_text(text)
                result["message"] = f"Typed text: {text}"
            
            elif command['command'] == 'scroll':
                clicks = command['params']['clicks']
                scroll(clicks)
                result["message"] = f"Scrolled by {clicks} clicks"
            elif command['command'] == 'remember':
                note = command['params'].get('text', '')
                if note:
                    mem = load_memory()
                    mem['learned'].append({"text": note, "date": datetime.now().strftime("%Y-%m-%d %H:%M")})
                    if len(mem['learned']) > LEARNED_MAX:
                        mem['learned'] = mem['learned'][-LEARNED_MAX:]
                    save_memory(mem)
                result["message"] = f"Remembered: {note[:60]}"
                results.append(result)
                continue

            elif command['command'] == 'add_note':
                from services.personal import add_note
                note = add_note(command['params'].get('text', ''))
                result["message"] = f"Note saved: {note[:60]}" if note else "Empty note"
                result["success"] = bool(note)
                results.append(result)
                continue

            elif command['command'] == 'list_notes':
                from services.personal import list_notes
                rows = list_notes(int(command['params'].get('limit') or 20))
                result["message"] = (
                    "\n".join(f"- {r['text']} ({r['date']})" for r in rows) if rows else "No notes yet"
                )
                results.append(result)
                continue

            elif command['command'] == 'set_profile':
                from services.personal import set_profile
                field = command['params'].get('field', 'name')
                value = set_profile(field, command['params'].get('value', ''))
                result["message"] = f"Profile {field} = {value}" if value else f"Could not set {field}"
                result["success"] = bool(value)
                results.append(result)
                continue

            elif command['command'] == 'save_routine':
                from services.personal import save_routine
                name = save_routine(command['params'].get('name', ''),
                                    command['params'].get('steps') or [])
                result["message"] = f"Routine '{name}' saved" if name else "Routine needs a name and steps"
                result["success"] = bool(name)
                results.append(result)
                continue

            elif command['command'] == 'list_routines':
                from services.personal import list_routines
                rows = list_routines()
                result["message"] = (
                    "\n".join(f"- {r['name']}: {'; '.join(r['steps'])}" for r in rows)
                    if rows else "No routines saved"
                )
                results.append(result)
                continue

            elif command['command'] == 'watch_screen_for':
                from services.watchers import add_text_watch
                target = command['params'].get('text', '')
                wid = add_text_watch(target)
                result["message"] = (
                    f"Watching the screen for '{target}'" if wid else "Could not start watcher"
                )
                result["success"] = bool(wid)
                results.append(result)
                continue

            elif command['command'] == 'watch_downloads':
                from services.watchers import add_download_watch
                wid = add_download_watch()
                result["message"] = "Watching Downloads" if wid else "Could not start watcher"
                result["success"] = bool(wid)
                results.append(result)
                continue

            elif command['command'] == 'answer':
                answer_text = command['params'].get('text', '')
                if answer_text:
                    try:
                        from services.tts import speak
                        speak(answer_text)
                    except Exception as e:
                        print(f"[TTS] Error: {e}")
                result["message"] = f"Answered: {answer_text[:80]}"
                results.append(result)
                set_listening(True)
                return results

            elif command['command'] == 'web_search':
                query = command['params'].get('query', '')
                try:
                    resp = _requests.get(
                        "https://html.duckduckgo.com/html/",
                        params={"q": query},
                        headers={"User-Agent": "Mozilla/5.0"},
                        timeout=8
                    )
                    # Extract text snippets from results
                    snippets = re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', resp.text, re.DOTALL)
                    clean = [re.sub(r'<[^>]+>', '', s).strip() for s in snippets[:5]]
                    search_result = "\n".join(clean) if clean else "No results found."
                    result["message"] = f"[SEARCH RESULTS for '{query}']:\n{search_result}"
                    print(f"[SEARCH] {query} -> {len(clean)} results")
                except Exception as e:
                    result["message"] = f"Search failed: {e}"
                    print(f"[SEARCH] Error: {e}")
                results.append(result)
                continue

            elif command['command'].startswith('browser_'):
                from services.browser_bridge import bridge_command, is_bridge_connected
                subcmd = command['command'][8:]
                if not is_bridge_connected():
                    result["success"] = False
                    result["message"] = "Chrome extension not connected. Install Aemyos extension in Chrome."
                    results.append(result)
                    continue

                if subcmd == 'get_text':
                    r = bridge_command('get_page_text')
                    if r.get('success'):
                        result["message"] = f"[PAGE TEXT] Title: {r.get('title','')}\nURL: {r.get('url','')}\n{r.get('text','')[:3000]}"
                    else:
                        result["success"] = False
                        result["message"] = r.get('error', 'Failed')

                elif subcmd == 'get_info':
                    r = bridge_command('get_page_info')
                    if r.get('success'):
                        info = r.get('info', {})
                        parts = [f"Title: {info.get('title','')}", f"URL: {info.get('url','')}"]
                        if info.get('buttons'):
                            parts.append("Buttons: " + ", ".join(b['text'] for b in info['buttons'][:15]))
                        if info.get('inputs'):
                            parts.append("Inputs: " + ", ".join(f"{i.get('label') or i.get('name') or i.get('placeholder','?')}({i['type']})" for i in info['inputs'][:10]))
                        if info.get('links'):
                            parts.append(f"Links: {len(info['links'])} found")
                        result["message"] = "[PAGE INFO]\n" + "\n".join(parts)
                    else:
                        result["success"] = False
                        result["message"] = r.get('error', 'Failed')

                elif subcmd == 'click':
                    params = command.get('params', {})
                    r = bridge_command('click_element', params)
                    result["success"] = r.get('success', False)
                    result["message"] = r.get('message', r.get('error', 'Click failed'))

                elif subcmd == 'fill':
                    params = command.get('params', {})
                    r = bridge_command('fill_input', params)
                    result["success"] = r.get('success', False)
                    result["message"] = r.get('message', r.get('error', 'Fill failed'))

                elif subcmd == 'navigate':
                    url = command['params'].get('url', '')
                    r = reuse_or_open_url(url, prefer_new=False)
                    result["success"] = r.get('success', False)
                    result["message"] = r.get('message', r.get('error', 'Navigate failed'))

                elif subcmd == 'new_tab':
                    url = (command.get('params') or {}).get('url') or 'chrome://newtab'
                    r = reuse_or_open_url(url, prefer_new=True)
                    result["success"] = r.get('success', False)
                    result["message"] = r.get('message', r.get('error', 'New tab failed'))

                elif subcmd == 'get_tabs':
                    r = bridge_command('get_tabs')
                    if r.get('success'):
                        result["message"] = _format_tabs_message(r.get('tabs', []))
                    else:
                        result["success"] = False
                        result["message"] = r.get('error', 'Failed')

                elif subcmd == 'extract':
                    params = command.get('params', {})
                    r = bridge_command('extract_data', params)
                    if r.get('success'):
                        if r.get('type') == 'table':
                            rows = r.get('rows', [])
                            table_text = "\n".join(" | ".join(cell[:30] for cell in row) for row in rows[:20])
                            result["message"] = f"[TABLE DATA] {len(rows)} rows:\n{table_text}"
                        elif r.get('type') == 'list':
                            items = r.get('items', [])
                            result["message"] = f"[LIST DATA] {len(items)} items:\n" + "\n".join(f"- {i}" for i in items[:20])
                        else:
                            result["message"] = f"[PAGE DATA]\n{r.get('text', '')[:2000]}"
                    else:
                        result["success"] = False
                        result["message"] = r.get('error', 'Failed')

                elif subcmd == 'get_links':
                    r = bridge_command('get_links')
                    if r.get('success'):
                        links = r.get('links', [])
                        link_text = "\n".join(f"  {l['text'][:50]} → {l['href'][:80]}" for l in links[:20])
                        result["message"] = f"[LINKS] {len(links)} found:\n{link_text}"
                    else:
                        result["success"] = False
                        result["message"] = r.get('error', 'Failed')

                elif subcmd == 'find_tab':
                    params = command.get('params', {})
                    r = _bridge_find_tab(bridge_command, params)
                    result["success"] = r.get('success', False)
                    result["message"] = r.get('message', r.get('error', 'Tab not found'))

                elif subcmd == 'get_bookmarks':
                    params = command.get('params', {})
                    r = bridge_command('get_bookmarks', params)
                    if r.get('success'):
                        bms = r.get('bookmarks', [])
                        bm_text = "\n".join(f"  {b['title'][:40]} → {b['url'][:60]}" for b in bms[:15])
                        result["message"] = f"[BOOKMARKS] {r.get('total', len(bms))} found:\n{bm_text}"
                    else:
                        result["success"] = False
                        result["message"] = r.get('error', 'Failed')

                elif subcmd == 'get_history':
                    params = command.get('params', {})
                    r = bridge_command('get_history', params)
                    if r.get('success'):
                        items = r.get('history', [])
                        hist_text = "\n".join(f"  {h['title'][:40]} | {h['lastVisit']}" for h in items[:15])
                        result["message"] = f"[HISTORY] {len(items)} entries:\n{hist_text}"
                    else:
                        result["success"] = False
                        result["message"] = r.get('error', 'Failed')

                elif subcmd == 'add_bookmark':
                    params = command.get('params', {})
                    r = bridge_command('add_bookmark', params)
                    result["success"] = r.get('success', False)
                    result["message"] = "Bookmarked!" if r.get('success') else r.get('error', 'Failed')

                else:
                    r = bridge_command(subcmd, command.get('params', {}))
                    result["success"] = r.get('success', False)
                    result["message"] = r.get('message', r.get('error', str(r)))

                results.append(result)
                continue

            elif command['command'] == 'clipboard_read':
                try:
                    text = pyperclip.paste()
                    result["message"] = f"[CLIPBOARD] {text[:500]}"
                except Exception as e:
                    result["success"] = False
                    result["message"] = f"Clipboard read failed: {e}"
                results.append(result)
                continue

            elif command['command'] == 'clipboard_write':
                try:
                    text = command['params'].get('text', '')
                    pyperclip.copy(text)
                    result["message"] = f"Copied to clipboard: {text[:80]}"
                except Exception as e:
                    result["success"] = False
                    result["message"] = f"Clipboard write failed: {e}"
                results.append(result)
                continue

            elif command['command'] == 'set_reminder':
                text = command['params'].get('text', 'Reminder')
                seconds = int(command['params'].get('seconds', 300))
                from services.smart_features import add_reminder
                fire_time = add_reminder(text, seconds)
                mins = seconds // 60
                result["message"] = f"Reminder set: '{text}' at {fire_time} ({mins}m from now)"
                results.append(result)
                continue

            elif command['command'] == 'volume_up':
                from services.smart_features import volume_up
                volume_up(command.get('params', {}).get('steps', 5))
                result["message"] = "Volume increased"
                results.append(result)
                continue

            elif command['command'] == 'volume_down':
                from services.smart_features import volume_down
                volume_down(command.get('params', {}).get('steps', 5))
                result["message"] = "Volume decreased"
                results.append(result)
                continue

            elif command['command'] == 'volume_mute':
                from services.smart_features import toggle_mute
                toggle_mute()
                result["message"] = "Toggled mute"
                results.append(result)
                continue

            elif command['command'] == 'get_running_apps':
                from services.smart_features import get_running_apps
                apps = get_running_apps()
                app_list = "\n".join(f"  {a['name']}: {a['title'][:50]}" for a in apps[:15])
                result["message"] = f"[RUNNING APPS] {len(apps)} windows:\n{app_list}"
                results.append(result)
                continue

            elif command['command'] == 'get_system_info':
                from services.smart_features import get_system_info
                info = get_system_info()
                parts = [f"Time: {info.get('time','?')}", f"CPU: {info.get('cpu',0)}%", f"RAM: {info.get('ram_pct',0)}% ({info.get('ram_gb',0)}GB/{info.get('ram_total_gb',0)}GB)"]
                if info.get('battery') is not None:
                    parts.append(f"Battery: {info['battery']}%{' ⚡' if info.get('charging') else ''}")
                result["message"] = "[SYSTEM] " + " | ".join(parts)
                results.append(result)
                continue

            elif command['command'] == 'clipboard_history':
                from services.smart_features import get_clipboard_history
                history = get_clipboard_history()
                if history:
                    items = "\n".join(f"  [{h['time']}] {h['text'][:60]}{'...' if h['full_len']>60 else ''}" for h in history[:10])
                    result["message"] = f"[CLIPBOARD HISTORY] {len(history)} items:\n{items}"
                else:
                    result["message"] = "[CLIPBOARD HISTORY] Empty"
                results.append(result)
                continue

            elif command['command'] == 'read_screen':
                from services.ocr import read_screen as _ocr_screen, ocr_available
                if not ocr_available():
                    result["success"] = False
                    result["message"] = "[OCR] Not available on this PC — read the screenshot instead."
                else:
                    lines, _meta = _ocr_screen()
                    if lines:
                        limit = int(command.get('params', {}).get('limit') or 120)
                        body = "\n".join(ln["text"] for ln in lines[:limit])
                        more = f"\n… {len(lines) - limit} more lines" if len(lines) > limit else ""
                        result["message"] = f"[SCREEN TEXT] {len(lines)} lines:\n{body}{more}"
                    else:
                        result["message"] = "[SCREEN TEXT] No text detected."
                results.append(result)
                continue

            elif command['command'] == 'find_text':
                from services.ocr import find_text as _ocr_find, ocr_available
                query = command.get('params', {}).get('text') or command.get('params', {}).get('query') or ""
                if not ocr_available():
                    result["success"] = False
                    result["message"] = "[OCR] Not available on this PC — read the screenshot instead."
                elif not query:
                    result["success"] = False
                    result["message"] = "find_text requires params.text"
                else:
                    hits = _ocr_find(query)
                    if hits:
                        shown = "\n".join(
                            f"  '{h['text'][:60]}' at ({h['x']},{h['y']})" for h in hits[:8]
                        )
                        result["message"] = f"[FOUND] '{query}' — {len(hits)} match(es):\n{shown}"
                    else:
                        result["success"] = False
                        result["message"] = f"[FOUND] '{query}' is not visible on screen."
                results.append(result)
                continue

            elif command['command'] == 'get_active_window':
                try:
                    import ctypes
                    hwnd = ctypes.windll.user32.GetForegroundWindow()
                    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                    buf = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                    result["message"] = f"[ACTIVE WINDOW] {buf.value}"
                except Exception as e:
                    result["success"] = False
                    result["message"] = f"Failed: {e}"
                results.append(result)
                continue

            elif command['command'] == 'run_command':
                from services.smart_features import run_shell_command
                cmd = command['params'].get('command', '')
                timeout = command['params'].get('timeout', 15)
                r = run_shell_command(cmd, timeout)
                result["success"] = r["success"]
                result["message"] = f"[SHELL] $ {cmd}\n{r['output']}"
                results.append(result)
                continue

            elif command['command'] == 'read_file':
                from services.smart_features import read_file
                path = command['params'].get('path', '')
                r = read_file(path)
                if r["success"]:
                    trunc = " (truncated)" if r.get("truncated") else ""
                    result["message"] = f"[FILE {r['size']}B{trunc}]\n{r['content']}"
                else:
                    result["success"] = False
                    result["message"] = f"Read failed: {r['error']}"
                results.append(result)
                continue

            elif command['command'] == 'write_file':
                from services.smart_features import write_file
                path = command['params'].get('path', '')
                content = command['params'].get('content', '')
                append = command['params'].get('append', False)
                r = write_file(path, content, append)
                if r["success"]:
                    result["message"] = f"Written {r['bytes']}B to {r['path']}"
                else:
                    result["success"] = False
                    result["message"] = f"Write failed: {r['error']}"
                results.append(result)
                continue

            elif command['command'] == 'list_files':
                from services.smart_features import list_files
                path = command['params'].get('path', '.')
                r = list_files(path)
                if r["success"]:
                    lines = []
                    for e in r["entries"]:
                        if e["type"] == "dir":
                            lines.append(f"  📁 {e['name']}/")
                        else:
                            sz = e["size"]
                            unit = "B"
                            if sz > 1024*1024:
                                sz = sz / (1024*1024); unit = "MB"
                            elif sz > 1024:
                                sz = sz / 1024; unit = "KB"
                            lines.append(f"  📄 {e['name']} ({sz:.0f}{unit})")
                    result["message"] = f"[DIR {r['path']}] {r['total']} items:\n" + "\n".join(lines)
                else:
                    result["success"] = False
                    result["message"] = f"List failed: {r['error']}"
                results.append(result)
                continue

            elif command['command'] == 'manage_window':
                from services.smart_features import manage_window
                action = command['params'].get('action', '')
                title = command['params'].get('title', None)
                r = manage_window(action, title)
                if r["success"]:
                    result["message"] = f"Window '{r['window']}' → {r['action']}"
                else:
                    result["success"] = False
                    result["message"] = r["error"]
                results.append(result)
                continue

            elif command['command'] == 'kill_process':
                from services.smart_features import kill_process
                name = command['params'].get('name', '')
                r = kill_process(name)
                result["success"] = r["success"]
                result["message"] = r.get("output", r.get("error", ""))
                results.append(result)
                continue

            elif command['command'] == 'open_url':
                from services.smart_features import open_url
                url = command['params'].get('url', '')
                r = open_url(url)
                result["success"] = r["success"]
                result["message"] = f"Opened {url}" if r["success"] else r["error"]
                results.append(result)
                continue

            elif command['command'] == 'network_info':
                from services.smart_features import get_network_info
                info = get_network_info()
                if info.get("connected"):
                    result["message"] = f"[NETWORK] WiFi: {info['ssid']} | Signal: {info['signal']} | Speed: {info['speed']} | IP: {info.get('public_ip','N/A')}"
                else:
                    result["message"] = "[NETWORK] Not connected to WiFi"
                results.append(result)
                continue

            elif command['command'] == 'set_brightness':
                from services.smart_features import set_brightness
                level = int(command['params'].get('level', 50))
                r = set_brightness(level)
                result["success"] = r["success"]
                result["message"] = f"Brightness set to {level}%" if r["success"] else r.get("error", "Failed")
                results.append(result)
                continue

            elif command['command'] == 'virtual_desktop':
                from services.smart_features import virtual_desktop
                action = command['params'].get('action', '')
                r = virtual_desktop(action)
                result["success"] = r["success"]
                result["message"] = r.get("action", r.get("error", ""))
                results.append(result)
                continue

            elif command['command'] == 'lock_screen':
                from services.smart_features import lock_screen
                r = lock_screen()
                result["success"] = r["success"]
                result["message"] = "Screen locked" if r["success"] else r.get("error", "Failed")
                results.append(result)
                continue

            elif command['command'] == 'notify':
                from services.smart_features import show_notification
                title = command['params'].get('title', 'Aemyos')
                message = command['params'].get('message', '')
                r = show_notification(title, message)
                result["success"] = r["success"]
                result["message"] = f"Notification sent: {title}"
                results.append(result)
                continue

            elif command['command'] == 'listen':
                if not listening:
                    set_listening(True)
                    result["success"] = True
                    result["message"] = f"Waiting for user instructions..."
                    results.append(result)
                return results
            else:
                result["success"] = False
                result["message"] = f"Unknown command: {command['command']}"
                results.append(result)
                break
        
        except KeyError as e:
            result["success"] = False
            result["message"] = f"Missing required parameter: {e}"
            results.append(result)
            set_listening(False)
            break
        except Exception as e:
            if type(e).__name__ == "FailSafeException" or "fail-safe" in str(e).lower():
                result["success"] = False
                result["message"] = (
                    "FAILSAFE: mouse hit a screen corner — aborted. "
                    "Move the pointer away from the corner and retry."
                )
                results.append(result)
                set_listening(True)
                break
            result["success"] = False
            result["message"] = f"Error executing command: {str(e)}"
            results.append(result)
            set_listening(False)
            break
        
        results.append(result)
        time.sleep(0.15)
    
    return results
