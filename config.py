import os

def _load_env():
    """Load .env file if it exists"""
    from services.paths import data_path
    env_path = data_path('.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    key, val = key.strip(), val.strip()
                    if not key:
                        continue
                    current = os.environ.get(key)
                    if current is None or not str(current).strip():
                        os.environ[key] = val

_load_env()

ANTHROPIC_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
OPENROUTER_KEY = os.environ.get('OPENROUTER_API_KEY', '')


def _resolve_provider():
    raw = (os.environ.get('DAVI_PROVIDER') or '').strip().lower()
    if raw in ('openrouter', 'or'):
        if OPENROUTER_KEY:
            return 'openrouter'
        if ANTHROPIC_KEY or GROQ_API_KEY:
            return 'anthropic'
        return 'openrouter'
    if raw in ('anthropic', 'direct', 'groq'):
        return 'anthropic'
    if OPENROUTER_KEY and not ANTHROPIC_KEY:
        return 'openrouter'
    return 'anthropic'


PROVIDER = _resolve_provider()

OPENROUTER_CHAT_URL = 'https://openrouter.ai/api/v1/chat/completions'
OPENROUTER_STT_URL = 'https://openrouter.ai/api/v1/audio/transcriptions'

OPENROUTER_LLM_MODELS = {
    'claude-sonnet-5': 'anthropic/claude-sonnet-5',
    'claude-opus-5': 'anthropic/claude-opus-5',
    'claude-haiku-4-5-20251001': 'anthropic/claude-haiku-4.5',
}

OPENROUTER_STT_MODELS = {
    'whisper-large-v3-turbo': 'openai/whisper-large-v3-turbo',
    'whisper-large-v3': 'openai/whisper-large-v3',
}


def using_openrouter():
    return PROVIDER == 'openrouter'


def llm_model_id():
    model = MODEL if 'MODEL' in globals() else os.environ.get('DAVI_MODEL', 'claude-sonnet-5')
    if using_openrouter():
        if '/' in str(model):
            return model
        return OPENROUTER_LLM_MODELS.get(model) or f'anthropic/{model}'
    return model


def stt_model_id():
    model = os.environ.get('DAVI_WHISPER_MODEL', WHISPER_MODEL if 'WHISPER_MODEL' in globals() else 'whisper-large-v3-turbo')
    if using_openrouter():
        if '/' in str(model):
            return model
        return OPENROUTER_STT_MODELS.get(model) or 'openai/whisper-large-v3'
    return model


def openrouter_headers():
    return {
        'Authorization': f'Bearer {OPENROUTER_KEY}',
        'HTTP-Referer': 'https://aemyos.ai',
        'X-OpenRouter-Title': 'Aemyos Desktop Agent',
        'Content-Type': 'application/json',
    }


def llm_ready():
    return bool(OPENROUTER_KEY) if using_openrouter() else bool(ANTHROPIC_KEY)


def stt_ready():
    """Voice is Groq or OpenRouter only. No local Whisper."""
    return bool(OPENROUTER_KEY) if using_openrouter() else bool(GROQ_API_KEY)


def keys_ready():
    return llm_ready() and stt_ready()

AVAILABLE_MODELS = {
    'claude-sonnet-5': 'Claude Sonnet 5 (Fast)',
    'claude-opus-5': 'Claude Opus 5 (Best)',
    'claude-haiku-4-5-20251001': 'Claude Haiku 4.5 (Cheapest)',
}

WHISPER_MODELS = {
    'whisper-large-v3-turbo': 'Whisper Large v3 Turbo (Default)',
    'whisper-large-v3': 'Whisper Large v3 (Most Accurate)',
}

MODEL = os.environ.get('DAVI_MODEL', 'claude-sonnet-5')
WHISPER_MODEL = os.environ.get('DAVI_WHISPER_MODEL', 'whisper-large-v3-turbo')
LANGUAGE = os.environ.get('DAVI_LANGUAGE', 'en')
THEME = os.environ.get('DAVI_THEME', 'dark')
VOICE_GENDER = os.environ.get('DAVI_VOICE_GENDER', 'female')
SYSTEM_PROMPT = 'default'
DAVI_VERSION = "1.8"

# Which display the agent looks at: cursor (monitor under the mouse),
# primary, virtual (all screens stitched), or a 1-based monitor index.
SCREENSHOT_MONITOR = os.environ.get('DAVI_SCREENSHOT_MONITOR', 'cursor')

# 'always' listens continuously; 'ptt' only records while the talk key is held.
LISTEN_MODE = os.environ.get('DAVI_LISTEN_MODE', 'always')
MIC_MUTED = os.environ.get('DAVI_MIC_MUTED', '0') == '1'
PTT_KEY = os.environ.get('DAVI_PTT_KEY', 'f9')

TTS_ENABLED = os.environ.get('DAVI_TTS_ENABLED', '1') != '0'
TTS_RATE = int(os.environ.get('DAVI_TTS_RATE', '0'))       # percent, -50..+50
TTS_VOLUME = int(os.environ.get('DAVI_TTS_VOLUME', '100'))  # percent, 0..100

# Subtract speaker playback from the mic so music is not treated as speech.
ECHO_CANCEL = os.environ.get('DAVI_ECHO_CANCEL', '1') != '0'

# speakers = laptop/room (mic hears playback). headphones = isolated mic.
_room = os.environ.get('DAVI_ROOM_AUDIO', 'speakers').lower().strip()
ROOM_AUDIO = 'headphones' if _room in ('headphones', 'headset', 'kulaklik', 'kulaklık') else 'speakers'

OPACITY = int(os.environ.get('DAVI_OPACITY', '100'))        # percent, 60..100
ALWAYS_ON_TOP = os.environ.get('DAVI_ALWAYS_ON_TOP', '1') != '0'


_RUNTIME_ENV = {
    'ANTHROPIC_API_KEY': 'ANTHROPIC_KEY',
    'GROQ_API_KEY': 'GROQ_API_KEY',
    'OPENROUTER_API_KEY': 'OPENROUTER_KEY',
    'DAVI_PROVIDER': 'PROVIDER',
    'DAVI_MODEL': 'MODEL',
    'DAVI_WHISPER_MODEL': 'WHISPER_MODEL',
}


def _apply_runtime(kwargs):
    g = globals()
    for k, v in kwargs.items():
        os.environ[str(k)] = '' if v is None else str(v)
        attr = _RUNTIME_ENV.get(k)
        if not attr:
            continue
        val = v
        if attr == 'PROVIDER':
            raw = str(v or '').strip().lower()
            val = 'openrouter' if raw in ('openrouter', 'or') else 'anthropic'
        g[attr] = val


def save_env(**kwargs):
    from services.paths import data_path
    env_path = data_path('.env')
    existing = {}
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    existing[k.strip()] = v.strip()
    existing.update(kwargs)
    with open(env_path, 'w') as f:
        for k, v in existing.items():
            f.write(f"{k}={v}\n")
    _apply_runtime(kwargs)
