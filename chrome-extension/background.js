const WS_URL = 'ws://localhost:8769';
const VERSION = '1.3.1';

let ws = null;
let connected = false;
let reconnectTimer = null;
let commandLog = [];
let lastError = '';
let lastErrorTime = '';
let reconnectAttempts = 0;
let agentLanguage = 'en';

function setLastError(err) {
  lastError = String(err || '');
  lastErrorTime = lastError ? new Date().toLocaleTimeString() : '';
}

function connect() {
  if (ws && ws.readyState <= 1) return;

  try {
    ws = new WebSocket(WS_URL);
  } catch (e) {
    setLastError('WebSocket create failed: ' + e.message);
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    connected = true;
    reconnectAttempts = 0;
    setLastError('');
    console.log('[Aemyos] Connected to agent');
    chrome.action.setBadgeText({ text: 'ON' });
    chrome.action.setBadgeBackgroundColor({ color: '#34d399' });
    try {
      ws.send(JSON.stringify({ type: 'hello', role: 'extension', version: VERSION }));
    } catch (e) {}
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  ws.onmessage = async (event) => {
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch (e) {
      return;
    }
    if (msg.language) agentLanguage = String(msg.language).toLowerCase();
    if (msg.type === 'status' || msg.type === 'pong' || msg.type === 'hello_ack') {
      return;
    }
    const cmdName = msg.command || 'unknown';
    const startTime = Date.now();
    const result = await handleCommand(msg);
    const elapsed = Date.now() - startTime;
    const ok = result?.success !== false;
    if (!ok) setLastError((result && result.error) || (cmdName + ' failed'));
    commandLog.unshift({ command: cmdName, time: new Date().toLocaleTimeString(), ms: elapsed, ok });
    if (commandLog.length > 20) commandLog.pop();
    try {
      ws.send(JSON.stringify({ id: msg.id, result }));
    } catch (e) {
      setLastError('Send error: ' + e.message);
      console.error('[Aemyos] Send error:', e);
    }
  };

  ws.onclose = () => {
    connected = false;
    ws = null;
    chrome.action.setBadgeText({ text: '' });
    scheduleReconnect();
  };

  ws.onerror = () => {
    setLastError('Cannot reach Aemyos at ' + WS_URL + '. Is the agent running?');
    try { ws.close(); } catch (e) {}
  };
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectAttempts += 1;
  const delay = Math.min(8000, 2000 + reconnectAttempts * 500);
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, delay);
}

function forceReconnect() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  reconnectAttempts = 0;
  if (ws) {
    try { ws.close(); } catch (e) {}
    ws = null;
  }
  connected = false;
  connect();
}

chrome.alarms.create('keepalive', { periodInMinutes: 0.25 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'keepalive' && !connected) connect();
});

function isRestrictedUrl(url) {
  if (!url) return true;
  return (
    url.startsWith('chrome://') ||
    url.startsWith('chrome-extension://') ||
    url.startsWith('edge://') ||
    url.startsWith('about:') ||
    url.startsWith('devtools://')
  );
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab || null;
}

function tabSummary(t) {
  return {
    id: t.id,
    title: t.title || '',
    url: t.url || '',
    active: !!t.active,
    windowId: t.windowId,
    pinned: !!t.pinned,
    audible: !!t.audible,
    muted: !!t.mutedInfo?.muted
  };
}

async function handleCommand(msg) {
  const { command, params = {} } = msg;

  try {
    switch (command) {
      case 'get_page_text':
        return await sendToContent('getPageText', params);

      case 'get_page_info':
        return await sendToContent('getPageInfo', params);

      case 'get_summary':
      case 'get_page_summary': {
        const r = await sendToContent('getPageSummary', params);
        if (r && r.success) {
          r.message = [
            `Title: ${r.title || ''}`,
            `URL: ${r.url || ''}`,
            `Selection: ${r.selection || '(none)'}`,
            r.headings && r.headings.length ? `Headings: ${r.headings.join(' | ')}` : '',
            r.text || ''
          ].filter(Boolean).join('\n');
        }
        return r;
      }

      case 'click_element':
        return await sendToContent('clickElement', params);

      case 'fill_input':
        return await sendToContent('fillInput', params);

      case 'select_option':
        return await sendToContent('selectOption', params);

      case 'get_links':
      case 'find_links': {
        const r = await sendToContent(command === 'find_links' ? 'findLinks' : 'getLinks', params);
        if (r && r.success && Array.isArray(r.links)) {
          const lines = r.links.slice(0, 25).map(l => `  ${l.text} → ${l.href}`);
          r.message = `[LINKS] ${r.count || r.links.length} found:\n${lines.join('\n')}`;
        }
        return r;
      }

      case 'get_forms': {
        const r = await sendToContent('getForms', params);
        if (r && r.success && Array.isArray(r.forms)) {
          r.message = `[FORMS] ${r.forms.length} form(s)`;
        }
        return r;
      }

      case 'read_element':
        return await sendToContent('readElement', params);

      case 'highlight_element':
        return await sendToContent('highlightElement', params);

      case 'scroll_to_element':
      case 'scroll_to':
        return await sendToContent('scrollToElement', params);

      case 'navigate': {
        const tab = await activeTab();
        if (!tab) return { success: false, error: 'No active tab' };
        await chrome.tabs.update(tab.id, { url: params.url });
        await waitTabComplete(tab.id);
        return { success: true, message: `Navigating to ${params.url}` };
      }

      case 'get_tabs': {
        const tabs = await chrome.tabs.query({});
        return { success: true, tabs: tabs.map(tabSummary), count: tabs.length };
      }

      case 'get_active_tab': {
        const tab = await activeTab();
        if (!tab) return { success: false, error: 'No active tab' };
        const info = tabSummary(tab);
        return { success: true, tab: info, message: `${info.title} | ${info.url} | id=${info.id}` };
      }

      case 'find_tab':
      case 'findTab':
      case 'focus_tab':
      case 'switch_tab': {
        if (params.tab_id) {
          const tab = await chrome.tabs.get(params.tab_id);
          await chrome.tabs.update(tab.id, { active: true });
          await chrome.windows.update(tab.windowId, { focused: true });
          return { success: true, message: `Switched to: ${tab.title}`, tab: tabSummary(tab) };
        }
        const query = (params.query || params.text || '').toLowerCase();
        if (!query) return { success: false, error: 'Provide tab_id or query' };
        const tabs = await chrome.tabs.query({});
        const matches = tabs.filter(t =>
          (t.title || '').toLowerCase().includes(query) ||
          (t.url || '').toLowerCase().includes(query)
        );
        if (matches.length > 0) {
          await chrome.tabs.update(matches[0].id, { active: true });
          await chrome.windows.update(matches[0].windowId, { focused: true });
          return { success: true, message: `Switched to: ${matches[0].title}`, tab: tabSummary(matches[0]) };
        }
        return { success: false, error: `No tab matching "${params.query || params.text}"` };
      }

      case 'new_tab': {
        const newTab = await chrome.tabs.create({ url: params.url || 'chrome://newtab' });
        if (params.url) await waitTabComplete(newTab.id);
        return { success: true, tab_id: newTab.id, message: `Opened tab ${newTab.id}` };
      }

      case 'close_tab': {
        if (params.tab_id) {
          await chrome.tabs.remove(params.tab_id);
        } else {
          const tab = await activeTab();
          if (tab) await chrome.tabs.remove(tab.id);
        }
        return { success: true, message: 'Tab closed' };
      }

      case 'reload_tab': {
        const tab = params.tab_id ? await chrome.tabs.get(params.tab_id) : await activeTab();
        if (!tab) return { success: false, error: 'No active tab' };
        await chrome.tabs.reload(tab.id);
        await waitTabComplete(tab.id);
        return { success: true, message: 'Tab reloaded' };
      }

      case 'go_back': {
        const tab = await activeTab();
        if (!tab) return { success: false, error: 'No active tab' };
        await chrome.tabs.goBack(tab.id);
        return { success: true, message: 'Went back' };
      }

      case 'go_forward': {
        const tab = await activeTab();
        if (!tab) return { success: false, error: 'No active tab' };
        await chrome.tabs.goForward(tab.id);
        return { success: true, message: 'Went forward' };
      }

      case 'duplicate_tab': {
        const tab = await activeTab();
        if (!tab) return { success: false, error: 'No active tab' };
        const dup = await chrome.tabs.duplicate(tab.id);
        return { success: true, tab_id: dup.id };
      }

      case 'pin_tab': {
        const tab = await activeTab();
        if (!tab) return { success: false, error: 'No active tab' };
        await chrome.tabs.update(tab.id, { pinned: !tab.pinned });
        return { success: true, pinned: !tab.pinned };
      }

      case 'mute_tab': {
        const tab = await activeTab();
        if (!tab) return { success: false, error: 'No active tab' };
        await chrome.tabs.update(tab.id, { muted: !tab.mutedInfo?.muted });
        return { success: true, muted: !tab.mutedInfo?.muted };
      }

      case 'zoom': {
        const tab = await activeTab();
        if (!tab) return { success: false, error: 'No active tab' };
        const current = await chrome.tabs.getZoom(tab.id);
        const delta = params.direction === 'out' ? -0.1 : 0.1;
        const level = params.level || Math.round((current + delta) * 10) / 10;
        await chrome.tabs.setZoom(tab.id, Math.max(0.25, Math.min(5, level)));
        return { success: true, zoom: level };
      }

      case 'get_bookmarks': {
        const tree = await chrome.bookmarks.getTree();
        const flat = [];
        function walk(nodes) {
          for (const n of nodes) {
            if (n.url) flat.push({ title: n.title, url: n.url });
            if (n.children) walk(n.children);
          }
        }
        walk(tree);
        const query = (params.query || '').toLowerCase();
        const filtered = query
          ? flat.filter(b => b.title.toLowerCase().includes(query) || b.url.toLowerCase().includes(query))
          : flat;
        return { success: true, bookmarks: filtered.slice(0, 50), total: filtered.length };
      }

      case 'add_bookmark': {
        const tab = await activeTab();
        const bm = await chrome.bookmarks.create({
          title: params.title || (tab ? tab.title : 'Untitled'),
          url: params.url || (tab ? tab.url : '')
        });
        return { success: true, bookmark: bm, message: 'Bookmarked' };
      }

      case 'get_history': {
        const items = await chrome.history.search({
          text: params.query || '',
          maxResults: params.limit || 20,
          startTime: params.hours_ago ? Date.now() - (params.hours_ago * 3600000) : 0
        });
        return {
          success: true,
          history: items.map(h => ({
            title: h.title,
            url: h.url,
            lastVisit: new Date(h.lastVisitTime).toLocaleString(),
            visits: h.visitCount
          }))
        };
      }

      case 'get_downloads': {
        const items = await chrome.downloads.search({ limit: params.limit || 10, orderBy: ['-startTime'] });
        return {
          success: true,
          downloads: items.map(d => ({
            filename: (d.filename || '').split(/[/\\]/).pop(),
            url: d.url,
            state: d.state,
            size: d.totalBytes,
            startTime: new Date(d.startTime).toLocaleString()
          }))
        };
      }

      case 'take_screenshot':
      case 'screenshot': {
        const windowId = params.window_id || null;
        const dataUrl = await chrome.tabs.captureVisibleTab(windowId, { format: 'png' });
        return {
          success: true,
          screenshot: dataUrl,
          message: 'Visible tab captured'
        };
      }

      case 'get_selection': {
        const r = await sendToContent('getSelection', params);
        if (r && r.success) r.message = r.text ? `[SELECTION] ${r.text}` : '[SELECTION] (empty)';
        return r;
      }

      case 'scroll_page':
        return await sendToContent('scrollPage', params);

      case 'extract_data':
        return await sendToContent('extractData', params);

      case 'wait_for_element':
      case 'wait_for_selector': {
        const r = await sendToContent('waitForElement', params);
        if (r && r.success) r.message = r.found ? `Found: ${r.text || params.selector || params.text}` : (r.error || 'Not found');
        return r;
      }

      case 'get_page_meta':
        return await sendToContent('getPageMeta', params);

      case 'ping':
        return { success: true, message: 'pong', connected: true, version: VERSION };

      default:
        return { success: false, error: `Unknown command: ${command}` };
    }
  } catch (e) {
    setLastError(e.message);
    return { success: false, error: e.message };
  }
}

function waitTabComplete(tabId, timeout = 15000) {
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      chrome.tabs.onUpdated.removeListener(listener);
      resolve();
    };
    const timer = setTimeout(finish, timeout);
    function listener(id, info) {
      if (id === tabId && info.status === 'complete') {
        clearTimeout(timer);
        finish();
      }
    }
    chrome.tabs.onUpdated.addListener(listener);
  });
}

async function sendToContent(action, params = {}) {
  const tab = await activeTab();
  if (!tab) return { success: false, error: 'No active tab' };
  if (isRestrictedUrl(tab.url)) {
    return { success: false, error: 'Cannot access Chrome internal pages' };
  }
  try {
    return await chrome.tabs.sendMessage(tab.id, { action, params });
  } catch (e) {
    try {
      await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['content.js'] });
      return await chrome.tabs.sendMessage(tab.id, { action, params });
    } catch (e2) {
      return { success: false, error: `Content script not ready: ${e2.message}` };
    }
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'getStatus') {
    sendResponse({
      connected,
      commandLog: commandLog.slice(0, 8),
      lastError,
      lastErrorTime,
      version: VERSION,
      wsUrl: WS_URL,
      language: agentLanguage
    });
    return true;
  }
  if (msg.action === 'reconnect') {
    forceReconnect();
    sendResponse({ ok: true, connected });
    return true;
  }
});

chrome.runtime.onInstalled.addListener(() => connect());
chrome.runtime.onStartup.addListener(() => connect());

connect();
