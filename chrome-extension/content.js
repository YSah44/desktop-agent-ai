chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const { action, params } = msg;

  try {
    switch (action) {
      case 'getPageText': {
        sendResponse({
          success: true,
          title: document.title,
          url: window.location.href,
          text: visibleText(8000)
        });
        break;
      }

      case 'getPageSummary': {
        const selection = window.getSelection().toString().trim();
        sendResponse({
          success: true,
          title: document.title,
          url: window.location.href,
          selection: selection.substring(0, 800),
          headings: [...document.querySelectorAll('h1,h2,h3')]
            .slice(0, 12)
            .map(h => h.innerText.trim().substring(0, 100))
            .filter(Boolean),
          text: visibleText(2000)
        });
        break;
      }

      case 'getPageInfo': {
        const info = {
          title: document.title,
          url: window.location.href,
          headings: [...document.querySelectorAll('h1,h2,h3')].slice(0, 20).map(h => ({
            level: h.tagName,
            text: h.innerText.trim().substring(0, 120)
          })),
          buttons: [...document.querySelectorAll('button, [role="button"], input[type="submit"], input[type="button"]')]
            .slice(0, 30).map(b => ({
              text: (b.innerText || b.value || b.getAttribute('aria-label') || '').trim().substring(0, 60),
              id: b.id || '',
              class: b.className ? String(b.className).substring(0, 60) : ''
            })).filter(b => b.text),
          inputs: [...document.querySelectorAll('input:not([type="hidden"]), textarea, select')]
            .slice(0, 30).map(i => ({
              type: i.type || i.tagName.toLowerCase(),
              name: i.name || '',
              id: i.id || '',
              placeholder: i.placeholder || '',
              value: i.type === 'password' ? '***' : (i.value || '').substring(0, 60),
              label: getInputLabel(i)
            })),
          links: [...document.querySelectorAll('a[href]')]
            .slice(0, 40).map(a => ({
              text: a.innerText.trim().substring(0, 100),
              href: a.href
            })).filter(l => l.text),
          meta: {
            description: getMeta('description'),
            viewport: getMeta('viewport')
          }
        };
        sendResponse({ success: true, info });
        break;
      }

      case 'clickElement': {
        const el = findElement(params) || youtubeSearchFallback(params);
        if (el) {
          realClick(el);
          sendResponse({
            success: true,
            message: `Clicked: ${(el.innerText || el.value || el.getAttribute('aria-label') || el.tagName).toString().substring(0, 60)}`
          });
        } else {
          sendResponse({ success: false, error: `Element not found: ${params.text || params.selector}` });
        }
        break;
      }

      case 'fillInput': {
        const el = findInput(params) || youtubeSearchFallback(params);
        if (el) {
          fillNative(el, params.value || params.text || '');
          if (params.submit) {
            const form = el.closest('form');
            if (form) {
              if (form.requestSubmit) form.requestSubmit();
              else form.submit();
            } else {
              el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true }));
            }
          }
          sendResponse({ success: true, message: `Filled: ${params.name || params.label || params.selector || 'input'}` });
        } else {
          sendResponse({ success: false, error: 'Input not found' });
        }
        break;
      }

      case 'selectOption': {
        const el = findInput(params) || (params.selector ? document.querySelector(params.selector) : null);
        if (!el || el.tagName !== 'SELECT') {
          sendResponse({ success: false, error: 'Select element not found' });
          break;
        }
        const wanted = (params.value || params.text || '').toLowerCase();
        let matched = false;
        for (const opt of el.options) {
          if (opt.value.toLowerCase() === wanted || opt.text.toLowerCase().includes(wanted)) {
            el.value = opt.value;
            matched = true;
            break;
          }
        }
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        sendResponse(matched
          ? { success: true, message: `Selected: ${el.value}` }
          : { success: false, error: 'Option not found' });
        break;
      }

      case 'getLinks':
      case 'findLinks': {
        const query = (params.query || params.text || '').toLowerCase();
        const links = [...document.querySelectorAll('a[href]')]
          .map(a => ({
            text: a.innerText.trim().substring(0, 120),
            href: a.href,
            visible: isVisible(a)
          }))
          .filter(l => l.text && l.href && !l.href.startsWith('javascript:'))
          .filter(l => !query || l.text.toLowerCase().includes(query) || l.href.toLowerCase().includes(query))
          .slice(0, 60);
        sendResponse({ success: true, count: links.length, links });
        break;
      }

      case 'getForms': {
        const forms = [...document.querySelectorAll('form')].map((f, i) => ({
          index: i,
          action: f.action,
          method: f.method,
          inputs: [...f.querySelectorAll('input:not([type="hidden"]), textarea, select')].map(inp => ({
            type: inp.type || inp.tagName.toLowerCase(),
            name: inp.name || inp.id || '',
            placeholder: inp.placeholder || '',
            required: inp.required,
            label: getInputLabel(inp)
          }))
        }));
        sendResponse({ success: true, forms });
        break;
      }

      case 'readElement': {
        const el = findElement(params);
        if (el) {
          sendResponse({
            success: true,
            tag: el.tagName,
            text: el.innerText?.substring(0, 3000) || '',
            html: el.innerHTML?.substring(0, 3000) || '',
            attributes: getAttributes(el)
          });
        } else {
          sendResponse({ success: false, error: 'Element not found' });
        }
        break;
      }

      case 'highlightElement': {
        const el = findElement(params);
        if (el) {
          const prev = el.style.outline;
          el.style.outline = '3px solid #6c8cff';
          el.style.outlineOffset = '2px';
          el.scrollIntoView({ behavior: 'smooth', block: 'center' });
          setTimeout(() => { el.style.outline = prev; el.style.outlineOffset = ''; }, 3000);
          sendResponse({ success: true, message: 'Element highlighted' });
        } else {
          sendResponse({ success: false, error: 'Element not found' });
        }
        break;
      }

      case 'scrollToElement': {
        const el = findElement(params);
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'center' });
          sendResponse({ success: true });
        } else {
          sendResponse({ success: false, error: 'Element not found' });
        }
        break;
      }

      case 'getSelection': {
        sendResponse({ success: true, text: window.getSelection().toString() });
        break;
      }

      case 'scrollPage': {
        const px = params.amount || 600;
        window.scrollBy({ top: params.direction === 'up' ? -px : px, behavior: 'smooth' });
        sendResponse({ success: true });
        break;
      }

      case 'extractData': {
        sendResponse(extractStructuredData(params));
        break;
      }

      case 'waitForElement': {
        const timeout = Math.min(params.timeout || 5000, 8000);
        const interval = 200;
        let elapsed = 0;
        const checker = setInterval(() => {
          const el = findElement(params);
          elapsed += interval;
          if (el) {
            clearInterval(checker);
            sendResponse({ success: true, found: true, text: el.innerText?.substring(0, 200) || '' });
          } else if (elapsed >= timeout) {
            clearInterval(checker);
            sendResponse({ success: false, found: false, error: 'Timeout waiting for element' });
          }
        }, interval);
        return true;
      }

      case 'getPageMeta': {
        const metas = {};
        document.querySelectorAll('meta').forEach(m => {
          const name = m.getAttribute('name') || m.getAttribute('property') || '';
          if (name && m.content) metas[name] = m.content.substring(0, 200);
        });
        sendResponse({
          success: true,
          title: document.title,
          url: window.location.href,
          lang: document.documentElement.lang,
          charset: document.characterSet,
          metas,
          canonical: document.querySelector('link[rel="canonical"]')?.href || '',
          favicon: document.querySelector('link[rel="icon"], link[rel="shortcut icon"]')?.href || ''
        });
        break;
      }

      default:
        sendResponse({ success: false, error: `Unknown action: ${action}` });
    }
  } catch (e) {
    sendResponse({ success: false, error: e.message });
  }
  return true;
});


function visibleText(limit) {
  const raw = document.body ? document.body.innerText : '';
  return raw.replace(/\n{3,}/g, '\n\n').trim().substring(0, limit);
}

function realClick(el) {
  if (el.tagName === 'LABEL' && el.control) el = el.control;
  el.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' });
  try { el.focus({ preventScroll: true }); } catch (e) {}
  const r = el.getBoundingClientRect();
  const x = r.left + Math.max(r.width / 2, 1);
  const y = r.top + Math.max(r.height / 2, 1);
  const opts = { bubbles: true, cancelable: true, composed: true, view: window, clientX: x, clientY: y, button: 0 };
  el.dispatchEvent(new PointerEvent('pointerdown', opts));
  el.dispatchEvent(new MouseEvent('mousedown', opts));
  el.dispatchEvent(new PointerEvent('pointerup', opts));
  el.dispatchEvent(new MouseEvent('mouseup', opts));
  el.dispatchEvent(new MouseEvent('click', opts));
  if (typeof el.click === 'function') el.click();
}

function fillNative(el, value) {
  if (el.isContentEditable) {
    el.focus();
    try {
      document.execCommand('selectAll', false, null);
      document.execCommand('insertText', false, value);
    } catch (e) {
      el.textContent = value;
    }
    el.dispatchEvent(new InputEvent('input', { bubbles: true, composed: true, data: value, inputType: 'insertText' }));
    return;
  }

  el.focus();
  try { el.click(); } catch (e) {}
  const proto = el.tagName === 'TEXTAREA'
    ? window.HTMLTextAreaElement.prototype
    : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
  if (setter) setter.call(el, value);
  else el.value = value;
  el.dispatchEvent(new InputEvent('input', { bubbles: true, cancelable: true, composed: true, data: value, inputType: 'insertText' }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

function findInput(params) {
  let el = null;
  if (params.selector) {
    el = document.querySelector(params.selector);
  } else if (params.name) {
    const name = params.name;
    el = document.querySelector(
      `[name="${cssAttr(name)}"], #${cssIdent(name)}, [placeholder*="${cssAttr(name)}" i], [aria-label*="${cssAttr(name)}" i]`
    );
  } else if (params.label) {
    const needle = params.label.toLowerCase();
    for (const lbl of document.querySelectorAll('label')) {
      if (lbl.innerText.toLowerCase().includes(needle)) {
        el = lbl.control || document.getElementById(lbl.htmlFor);
        break;
      }
    }
  }
  if (!el) {
    const inputs = document.querySelectorAll('input:not([type="hidden"]), textarea, select, [contenteditable="true"]');
    if (params.index !== undefined && inputs[params.index]) el = inputs[params.index];
  }
  if (!el) el = youtubeSearchFallback(params);
  return el;
}

function findElement(params) {
  if (params.selector) {
    const els = [...document.querySelectorAll(params.selector)];
    const idx = params.index || 0;
    const el = els.filter(isVisible)[idx] || els[idx] || null;
    if (el && isVisible(el)) return el;
    return youtubeSearchFallback(params);
  }
  if (params.id) {
    const byId = document.getElementById(params.id);
    if (byId) return byId;
    return youtubeSearchFallback(params);
  }
  if (params.text) {
    const searchText = params.text.toLowerCase();
    const candidates = document.querySelectorAll(
      'a, button, [role="button"], input[type="submit"], input[type="button"], [onclick], li, span, div, p, h1, h2, h3, h4, td, th, label'
    );
    let best = null;
    let bestLen = Infinity;
    for (const el of candidates) {
      const t = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
      if (t.toLowerCase().includes(searchText) && t.length < bestLen && isVisible(el)) {
        best = el;
        bestLen = t.length;
      }
    }
    return best || youtubeSearchFallback(params);
  }
  return youtubeSearchFallback(params);
}

function looksLikeSearch(params) {
  const blob = [params.selector, params.id, params.name, params.label, params.text]
    .filter(Boolean).join(' ').toLowerCase();
  return /search|#search|search_query|\bara\b/.test(blob);
}

function youtubeSearchInput() {
  const host = (location.hostname || '').toLowerCase();
  if (!host.includes('youtube.com') && host !== 'youtu.be') return null;
  const sels = [
    'input[name="search_query"]',
    'ytd-searchbox input',
    '#search-input input',
    'input[aria-label*="Search" i]',
    'input[aria-label*="Ara" i]',
    '#search input',
    'input#search'
  ];
  for (const s of sels) {
    const el = document.querySelector(s);
    if (el && isVisible(el)) return el;
  }
  const box = document.querySelector('ytd-searchbox');
  const inner = box ? box.querySelector('input') : null;
  return inner && isVisible(inner) ? inner : null;
}

function youtubeSearchFallback(params) {
  if (!looksLikeSearch(params || {})) return null;
  return youtubeSearchInput();
}

function isVisible(el) {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  if (r.width === 0 && r.height === 0) return false;
  const style = window.getComputedStyle(el);
  return style.display !== 'none' && style.visibility !== 'hidden' && parseFloat(style.opacity || '1') !== 0;
}

function getInputLabel(input) {
  if (input.id) {
    const label = document.querySelector(`label[for="${cssAttr(input.id)}"]`);
    if (label) return label.innerText.trim().substring(0, 60);
  }
  const parent = input.closest('label');
  if (parent) return parent.innerText.trim().substring(0, 60);
  const prev = input.previousElementSibling;
  if (prev && prev.tagName === 'LABEL') return prev.innerText.trim().substring(0, 60);
  return input.getAttribute('aria-label') || '';
}

function getMeta(name) {
  const el = document.querySelector(`meta[name="${name}"]`);
  return el ? el.content : '';
}

function getAttributes(el) {
  const attrs = {};
  for (const attr of el.attributes) {
    if (attr.name !== 'style' && attr.value.length < 200) {
      attrs[attr.name] = attr.value;
    }
  }
  return attrs;
}

function cssAttr(value) {
  return String(value).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
}

function cssIdent(value) {
  try {
    return CSS.escape(value);
  } catch (e) {
    return String(value).replace(/[^a-zA-Z0-9_-]/g, '\\$&');
  }
}

function extractStructuredData(params) {
  const type = params.type || 'auto';

  if (type === 'table' || type === 'auto') {
    const tables = document.querySelectorAll('table');
    if (tables.length > 0) {
      const idx = params.table_index || 0;
      const table = tables[idx];
      if (table) {
        const rows = [...table.querySelectorAll('tr')].slice(0, 100).map(tr =>
          [...tr.querySelectorAll('td, th')].map(cell => cell.innerText.trim())
        );
        return { success: true, type: 'table', rows, count: rows.length };
      }
    }
  }

  if (type === 'list' || type === 'auto') {
    const lists = document.querySelectorAll('ul, ol');
    if (lists.length > 0) {
      const items = [];
      lists.forEach(list => {
        [...list.querySelectorAll(':scope > li')].slice(0, 50).forEach(li => {
          items.push(li.innerText.trim().substring(0, 200));
        });
      });
      if (items.length > 0) return { success: true, type: 'list', items, count: items.length };
    }
  }

  if (type === 'article' || type === 'auto') {
    const article = document.querySelector('article, [role="main"], main, .content, .post');
    if (article) {
      return { success: true, type: 'article', text: article.innerText.substring(0, 5000) };
    }
  }

  return { success: true, type: 'text', text: visibleText(5000) };
}
