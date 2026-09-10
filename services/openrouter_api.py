import requests
import time
import threading
import json
import os

import config as _cfg

_prompt_cache = {}
_prompt_cache_lock = threading.Lock()

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


def _compact_history(messages, keep=8):
    """Keep recent turns. Drop images except the latest screenshot."""
    if not messages:
        return messages
    if len(messages) > keep:
        messages = messages[-keep:]
    last_image_idx = None
    for i, msg in enumerate(messages):
        for item in msg.get("content", []):
            if isinstance(item, dict) and item.get("type") == "image_url":
                last_image_idx = i
    compacted = []
    for i, msg in enumerate(messages):
        if i == last_image_idx:
            compacted.append(msg)
            continue
        new_content = []
        stripped = False
        for item in msg.get("content", []):
            if isinstance(item, dict) and item.get("type") == "image_url":
                if not stripped:
                    new_content.append({"type": "text", "text": "[previous screenshot omitted]"})
                    stripped = True
            else:
                new_content.append(item)
        compacted.append({**msg, "content": new_content})
    return compacted


def generate(messages, prompt, replace_dict=None):
    from services.paths import res_path, data_path
    prompt_path = res_path('prompts', f'{prompt}.md')
    with _prompt_cache_lock:
        with open(prompt_path, encoding='utf8') as f:
            system_message = f.read()

    if replace_dict:
        for key in list(replace_dict.keys()):
            if replace_dict[key]:
                system_message = system_message.replace(key, replace_dict[key])

    # Load memory and append to system prompt
    try:
        mem_path = data_path("memory.json")
        with open(mem_path, 'r', encoding='utf-8') as f:
            memory = json.load(f)
        mem_section = "\n\n## YOUR MEMORY\n"
        if memory.get("user"):
            u = memory["user"]
            mem_section += f"User: {u.get('name', 'Unknown')} — {u.get('role', '')} from {u.get('location', '')}\n"
        if memory.get("preferences"):
            p = memory["preferences"]
            if p.get("favorite_apps"):
                mem_section += f"Favorite apps: {', '.join(p['favorite_apps'])}\n"
                mem_section += "To open a favorite (or any installed app), use open_app with that name.\n"
        lt = memory.get("last_task") or {}
        if lt.get("status") == "unfinished" and lt.get("text"):
            mem_section += (
                f"Unfinished desktop task: {lt['text']}\n"
                "If the user says continue / devam et, resume THIS task from where you left off.\n"
            )
        if memory.get("learned"):
            recent = memory["learned"][-10:]
            if recent:
                mem_section += "Things you learned:\n"
                for item in recent:
                    mem_section += f"- {item['text']}\n"
        notes = memory.get("notes") or []
        user_notes = []
        for note in notes[-8:]:
            text = note.get("text") if isinstance(note, dict) else str(note)
            if text and not str(text).startswith(("▶ ", "📞 ")):
                user_notes.append(text)
        if user_notes:
            mem_section += "Notes the user asked you to keep:\n"
            for text in user_notes:
                mem_section += f"- {text}\n"
        try:
            from services.personal import life_prompt_lines
            life_lines = life_prompt_lines(memory)
        except Exception:
            life_lines = []
        if life_lines:
            mem_section += "\n".join(life_lines) + "\n"
        try:
            from services.context_facts import prompt_lines as _ctx_lines
            ctx = _ctx_lines()
        except Exception:
            ctx = []
        if ctx:
            mem_section += "\n".join(ctx) + "\n"
        system_message += mem_section
    except Exception:
        pass

    try:
        from services.i18n import language_prompt
        system_message = system_message.replace("{{LANGUAGE_INSTRUCTION}}", language_prompt())
    except Exception:
        system_message = system_message.replace(
            "{{LANGUAGE_INSTRUCTION}}",
            "ALWAYS respond in English. JSON command names stay in English.",
        )

    messages = _compact_history(messages)
    print('generating...')
    start_time = time.time()
    last_error = "Error generating response."
    use_or = _cfg.using_openrouter()

    for attempt in (1, 2):
        try:
            if use_or:
                data, http_err = _post_openrouter(system_message, messages)
            else:
                data, http_err = _post_anthropic(system_message, messages)
            elapsed = time.time() - start_time
            print(f"LLM response time: {elapsed:.2f}s (attempt {attempt})")

            if http_err:
                print(f"[API ERROR] {http_err}")
                last_error = "Error generating response."
                if attempt == 1:
                    print("[API] Retrying generate() once after error...")
                    time.sleep(0.7)
                    continue
                return last_error

            text = _extract_text(data, use_or)
            if not text or not str(text).strip():
                print(f"[API] Empty/unexpected content: {data}")
                last_error = "Error: no text in response."
                if attempt == 1:
                    print("[API] Retrying generate() once after empty response...")
                    time.sleep(0.7)
                    continue
                return last_error
            return text

        except Exception as e:
            print(f"Error in API call: {e}")
            last_error = "Error generating response. Please try again."
            if attempt == 1:
                print("[API] Retrying generate() once after exception...")
                time.sleep(0.7)
                continue
            return last_error

    return last_error


def _openai_messages(messages):
    out = []
    for msg in messages:
        role = msg.get("role")
        content = []
        for item in msg.get("content", []):
            if isinstance(item, dict):
                if item.get("type") == "text":
                    content.append({"type": "text", "text": item.get("text", "")})
                elif item.get("type") == "image_url":
                    content.append(item)
            elif isinstance(item, str):
                content.append({"type": "text", "text": item})
        if content:
            out.append({"role": role, "content": content})
    return out


def _anthropic_messages(messages):
    api_messages = []
    for msg in messages:
        role = msg["role"]
        content = []
        for item in msg.get("content", []):
            if isinstance(item, dict):
                if item.get("type") == "text":
                    content.append({"type": "text", "text": item["text"]})
                elif item.get("type") == "image_url":
                    url = item["image_url"]["url"]
                    if url.startswith("data:"):
                        media_type = url.split(";")[0].split(":")[1]
                        data = url.split(",", 1)[1]
                        content.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": data,
                            },
                        })
            elif isinstance(item, str):
                content.append({"type": "text", "text": item})
        if content:
            api_messages.append({"role": role, "content": content})
    return api_messages


def _post_anthropic(system_message, messages):
    resp = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": _cfg.ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": _cfg.MODEL,
            "system": system_message,
            "messages": _anthropic_messages(messages),
            "max_tokens": 1024,
        },
        timeout=45,
    )
    try:
        data = resp.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    if resp.status_code >= 400 or data.get("type") == "error":
        err = (data.get("error") or {}).get("message") or f"HTTP {resp.status_code}"
        return data, err
    return data, None


def _post_openrouter(system_message, messages):
    or_messages = [{"role": "system", "content": system_message}]
    or_messages.extend(_openai_messages(messages))
    resp = requests.post(
        _cfg.OPENROUTER_CHAT_URL,
        headers=_cfg.openrouter_headers(),
        json={
            "model": _cfg.llm_model_id(),
            "messages": or_messages,
            "max_tokens": 1024,
        },
        timeout=45,
    )
    try:
        data = resp.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    err = data.get("error")
    if resp.status_code >= 400 or err:
        if isinstance(err, dict):
            msg = err.get("message") or f"HTTP {resp.status_code}"
        else:
            msg = str(err or f"HTTP {resp.status_code}")
        return data, msg
    return data, None


def _extract_text(data, use_openrouter):
    if use_openrouter:
        choices = data.get("choices") or []
        if not choices:
            return ""
        message = (choices[0] or {}).get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text") or "")
                elif isinstance(block, str):
                    parts.append(block)
            return "".join(parts)
        return ""
    text = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            text = block["text"]
            break
    return text
