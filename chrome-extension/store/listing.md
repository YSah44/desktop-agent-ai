# Chrome Web Store listing — Aemyos Bridge

Upload file: `dist\Aemyos-Chrome-Extension-store.zip` (manifest.json at the zip root).
Images: `screenshot-1.png`, `screenshot-2.png` (1280x800), `promo-440x280.png` (small tile). Icon comes from the manifest.

## Store listing

**Name:** Aemyos Bridge

**Summary (≤132 chars):**
Local bridge for the Aemyos desktop voice agent: read pages, click, fill forms and manage tabs in your own Chrome by voice.

**Category:** Productivity · **Language:** English (also localized: Turkish, Spanish, German, French)

**Description:**
Aemyos Bridge connects Google Chrome to Aemyos, a free, open-source Windows desktop voice agent (aemyos.ai). With the extension installed, things you say to Aemyos that involve the browser — "open a new tab and search flights to Istanbul", "click Sign in", "scroll down", "fill the form with my name", "close this tab" — are carried out precisely inside Chrome instead of by simulated keyboard and mouse.

What it does
• Reads the current page so the agent can find buttons, links and fields by name
• Clicks elements, types into fields and submits forms on your command
• Opens, closes, switches, reloads and pins tabs; navigates back/forward; zooms
• Looks up your bookmarks, history and downloads when you ask for them
• Takes a screenshot of the visible tab for the agent when a task needs it

How it works
The extension talks only to the Aemyos app running on the same PC over a local WebSocket (ws://localhost:8769). It never contacts any web server of its own, has no analytics, sets no cookies and stores no personal data. Nothing happens unless you gave Aemyos a command. Without the desktop app the extension does nothing.

Requirements
• Windows 10/11 with Aemyos installed (free download at aemyos.ai/download.html, or run from source: github.com/YSah44/desktop-agent-ai)
• Your own Anthropic and Groq API keys, entered in the Aemyos app

Open source under the MIT license: github.com/YSah44/desktop-agent-ai/tree/main/chrome-extension

**Homepage URL:** https://aemyos.ai
**Support URL:** https://aemyos.ai/contact.html
**Privacy policy URL:** https://aemyos.ai/privacy.html

## Privacy practices tab

**Single purpose:** Let the Aemyos desktop voice agent, running on the same computer, read and control the user's own Chrome tabs on the user's spoken command.

**Permission justifications**
- `tabs`: open, close, switch, reload, pin and navigate tabs; report the current tab's title and URL to the local agent.
- `activeTab` / `scripting`: inject the content script into the current tab so the agent can find and click elements and fill fields the user asked for.
- `host_permissions <all_urls>` and content script on all URLs: the user can ask the agent to act on any site they are visiting; the extension cannot know in advance which site that will be. It acts only when the local agent sends a command.
- `bookmarks`: list and add bookmarks when the user asks ("bookmark this page", "open my bookmark X").
- `history`: search browsing history when the user asks ("open the page I visited yesterday about …").
- `downloads`: list recent downloads when the user asks ("open my last download").
- `alarms`: keep the service worker's local WebSocket connection to the desktop app alive (periodic reconnect).
- `clipboardWrite`: the popup's "Copy URL" button.

**Remote code:** No. All code is packaged in the extension.

**Data usage:** The extension does not collect or transmit any user data to the developer or third parties. Website content and tab metadata are passed only to the Aemyos application on the same computer over localhost, solely to perform the task the user requested. Certify: data is not sold, not used for purposes unrelated to the extension's single purpose, and not used to determine creditworthiness.

## Distribution
Visibility: Public · Regions: all.
