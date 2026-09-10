# Aemyos — Windows desktop AI agent

**Aemyos** is a native **Windows desktop AI voice agent**. An always-on-top overlay sees your screen, listens to the microphone, and drives the PC: apps, clicks, keys, volume, Explorer, and Chrome.

This GitHub repository is **`desktop-agent-ai`**. Product site: **[aemyos.ai](https://aemyos.ai)**.

| | |
| --- | --- |
| Product | [Aemyos](https://aemyos.ai) |
| GitHub | [github.com/YSah44/desktop-agent-ai](https://github.com/YSah44/desktop-agent-ai) |
| OS | Windows 10 / 11 |
| Stack | Python, Anthropic Claude, Groq speech, optional Chrome extension |
| Version | 1.8 |

<p align="center">
  <a href="https://github.com/YSah44/desktop-agent-ai/releases/latest/download/Aemyos-Setup.exe"><img src="https://img.shields.io/badge/Download-Aemyos--Setup.exe%20%C2%B7%20Windows%2010%2F11-7c93ff?style=for-the-badge&logo=windows&logoColor=white" alt="Download Aemyos for Windows"></a>
</p>
<p align="center">
  <a href="https://github.com/YSah44/desktop-agent-ai/releases/latest"><img src="https://img.shields.io/github/v/release/YSah44/desktop-agent-ai?label=release&color=7c93ff" alt="Latest release"></a>
  <a href="https://github.com/YSah44/desktop-agent-ai/releases"><img src="https://img.shields.io/github/downloads/YSah44/desktop-agent-ai/total?label=downloads&color=2ea043" alt="Downloads"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT"></a>
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776ab?logo=python&logoColor=white" alt="Python 3.10+">
</p>
<p align="center">No Python needed for the installer · open source, run from source with Python if you prefer</p>

<p align="center">
  <img src="docs/app-full.png" alt="Aemyos Windows desktop AI agent overlay" width="280">
  &nbsp;
  <img src="docs/app-compact.png" alt="Aemyos face-mode voice assistant" width="200">
</p>

The app is free. You bring your own [Anthropic](https://console.anthropic.com/) and [Groq](https://console.groq.com/) keys (or one [OpenRouter](https://openrouter.ai/) key). Those bills stay on your accounts. **This repository never contains API keys.**

## Windows desktop AI agent (what it does)

Aemyos is a **computer-use / desktop automation** voice assistant that runs on the machine, not in a browser tab:

- Always-on-top overlay, face mode, hide to tray
- Voice in, spoken replies out (Microsoft Edge TTS)
- Screen vision — ask “what’s on my screen?”
- Opens apps, clicks real UI, types, Explorer, Settings, lock, sleep
- Optional **Chrome extension** for tabs, forms, and clicks in Chrome
- English, Turkish, Spanish, German, French
- Destructive actions (empty Recycle Bin, shutdown) need a spoken confirm

Without the Chrome extension it still uses the keyboard and the screen.

## Download (Windows installer)

**[Aemyos-Setup-1.8.exe](https://github.com/YSah44/desktop-agent-ai/releases/latest/download/Aemyos-Setup.exe)** — Windows 10 / 11, **no Python needed**. Download, double-click, Next. On first start paste your keys in Settings (kept in `%APPDATA%\Aemyos\.env`).

SHA256 of `Aemyos-Setup-1.8.exe`:

```
324987202fa9b8e85cf5735c67974bfc5b3c22937d8bf6d19169e656db96f2c4
```

Check it in PowerShell: `Get-FileHash Aemyos-Setup-1.8.exe -Algorithm SHA256` — all releases: [releases](https://github.com/YSah44/desktop-agent-ai/releases).

The installer, `Aemyos.exe` and the uninstaller are code-signed with a Microsoft-verified certificate (Azure Trusted Signing, publisher *david sahbaz*). Right-click the file → Properties → Digital Signatures to check.

Build it yourself: `build.bat` (PyInstaller + Inno Setup) → `dist\Aemyos-Setup-1.8.exe`.

## Install from source (developers)

### 1. Python 3.10+

Install from [python.org](https://www.python.org/downloads/windows/). Enable **Add python.exe to PATH**.

### 2. Clone this repo

```bat
git clone https://github.com/YSah44/desktop-agent-ai.git
cd desktop-agent-ai
```

ZIP: [Download ZIP](https://github.com/YSah44/desktop-agent-ai/archive/refs/heads/main.zip)

### 3. One-click setup

Double-click **`install.bat`**.

It will:

1. Create a local `venv`
2. Install `requirements.txt`
3. Copy `.env.example` → `.env` (if you do not already have one)
4. Open Notepad so you can paste **your** keys

Do not commit `.env`. Do not paste keys into GitHub issues.

### 4. Keys

| Key | Where | Used for |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com/) | Thinking / vision |
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com/) | Speech recognition |
| `OPENROUTER_API_KEY` | optional | One key for think + listen if `DAVI_PROVIDER=openrouter` |

### 5. Run

Double-click **`start.bat`**. Overlay appears. Speak. Say **stop** or **Ctrl+Shift+Q** to quit.

```bat
venv\Scripts\python.exe -u main.py
```

## Chrome extension (optional)

Folder in this repo: [`chrome-extension`](https://github.com/YSah44/desktop-agent-ai/tree/main/chrome-extension)

1. Run `setup_extension.bat` or open `chrome://extensions`
2. Enable Developer mode
3. Load unpacked → the `chrome-extension` folder

## Safety

- Recycle Bin empty / PC restart require a spoken confirm
- Mic mute and push-to-talk live in Settings
- Developer preview: it can click and type on your desktop. Use a PC you own.

## Donate

If this helps, a gift covers time and API bills.

<a href="https://www.buymeacoffee.com/aemyos"><img src="https://img.buymeacoffee.com/button-api/?text=Buy%20me%20a%20coffee&emoji=%E2%98%95&slug=aemyos&button_colour=FFDD00&font_colour=000000&font_family=Cookie&outline_colour=000000&coffee_colour=ffffff" alt="Buy me a coffee" height="48"></a>

Prefer crypto? Each coin to its own address — [aemyos.ai/donate.html](https://aemyos.ai/donate.html)

**Bitcoin**

<img src="https://api.qrserver.com/v1/create-qr-code/?size=96x96&data=bitcoin:bc1qrx62dfggt9hsgpvtgd666adylpnc9dr2jr6tqn" width="80" height="80" alt="BTC">

`bc1qrx62dfggt9hsgpvtgd666adylpnc9dr2jr6tqn`

**Solana**

<img src="https://api.qrserver.com/v1/create-qr-code/?size=96x96&data=solana:5UBEsAtqgTmAPhjEgrJ4NgSKXZJQ6QkcpbNL5LiVyUBC" width="80" height="80" alt="SOL">

`5UBEsAtqgTmAPhjEgrJ4NgSKXZJQ6QkcpbNL5LiVyUBC`

**ETH / EVM**

<img src="https://api.qrserver.com/v1/create-qr-code/?size=96x96&data=ethereum:0x76E0Ab339ce38Cd3174a4096C5CaDb7cd587a00e" width="80" height="80" alt="ETH">

`0x76E0Ab339ce38Cd3174a4096C5CaDb7cd587a00e`

Ethereum, Base, Arbitrum, Optimism, Polygon, BNB Chain, Avalanche.

## License

Developer preview. Use on a machine you own. You are responsible for what you ask it to do.

Questions: [aemyos.ai/contact.html](https://aemyos.ai/contact.html) · `support@aemyos.ai`
