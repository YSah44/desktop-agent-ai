const $ = (id) => document.getElementById(id);
const t = (key) => AemyosI18n.t(key);

function paintUi() {
  AemyosI18n.apply();
  AemyosI18n.paintLangButtons($("lang-switch"));
  $("lang-switch").onLangChange = () => {
    AemyosI18n.apply();
    AemyosI18n.paintLangButtons($("lang-switch"));
    updateStatus();
  };
}

async function updateStatus() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab) {
      const title = tab.title || t("unknown");
      $("tab-info").textContent = title.length > 42 ? title.slice(0, 42) + "…" : title;
      try {
        $("tab-url").textContent = tab.url ? new URL(tab.url).hostname : "—";
      } catch (e) {
        $("tab-url").textContent = (tab.url || "—").slice(0, 40);
      }
    }
  } catch (e) {
    $("tab-info").textContent = "—";
  }

  try {
    const response = await chrome.runtime.sendMessage({ action: "getStatus" });
    if (response && response.language) AemyosI18n.followAgent(response.language);
    AemyosI18n.apply();
    AemyosI18n.paintLangButtons($("lang-switch"));

    const connected = !!(response && response.connected);
    const badge = $("badge");
    badge.className = "badge " + (connected ? "on" : "off");
    $("badge-text").textContent = connected ? t("connected") : t("offline");
    $("ws-status").textContent = connected ? t("connected") : t("disconnected");
    if (response && response.version) {
      $("version").textContent = "v" + response.version + " · " + t("bridge_name");
    }

    const errEl = $("last-error");
    if (response && response.lastError) {
      errEl.hidden = false;
      let err = response.lastError;
      if (/Cannot reach Aemyos|WebSocket create failed|Is the agent running/i.test(err)) {
        err = t("agent_off_err");
      }
      errEl.textContent = (response.lastErrorTime ? response.lastErrorTime + " · " : "") + err;
    } else {
      errEl.hidden = true;
      errEl.textContent = "";
    }

    const logEl = $("cmd-log");
    if (response && response.commandLog && response.commandLog.length) {
      logEl.innerHTML = response.commandLog.map((c) =>
        `<div class="log-item">
          <span class="log-cmd">${escapeHtml(c.command)}</span>
          <span><span class="${c.ok ? "ok" : "fail"}">${c.ok ? c.ms + "ms" : t("fail")}</span> <span class="log-time">${escapeHtml(c.time || "")}</span></span>
        </div>`
      ).join("");
    } else {
      logEl.innerHTML = `<div class="empty">${t("no_cmds")}</div>`;
    }
  } catch (e) {
    $("badge").className = "badge off";
    $("badge-text").textContent = t("error");
    $("ws-status").textContent = t("sw_error");
  }
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function flash(btn, text, ok) {
  const prev = btn.getAttribute("data-i18n") ? t(btn.getAttribute("data-i18n")) : btn.textContent;
  btn.textContent = text;
  btn.style.color = ok === false ? "#f87171" : ok ? "#34d399" : "";
  setTimeout(() => {
    btn.textContent = prev;
    btn.style.color = "";
    btn.disabled = false;
  }, 1800);
}

$("test-btn").addEventListener("click", async () => {
  const btn = $("test-btn");
  btn.disabled = true;
  btn.textContent = t("testing");
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.url || tab.url.startsWith("chrome://") || tab.url.startsWith("edge://")) {
      flash(btn, t("internal"), false);
      return;
    }
    let result;
    try {
      result = await chrome.tabs.sendMessage(tab.id, { action: "getPageSummary", params: {} });
    } catch (e) {
      await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
      result = await chrome.tabs.sendMessage(tab.id, { action: "getPageSummary", params: {} });
    }
    if (result && result.success) {
      flash(btn, t("page_ok"), true);
    } else {
      flash(btn, t("script_err"), false);
    }
  } catch (e) {
    flash(btn, t("failed"), false);
  }
});

$("reconnect-btn").addEventListener("click", async () => {
  const btn = $("reconnect-btn");
  btn.disabled = true;
  btn.textContent = t("connecting");
  try {
    await chrome.runtime.sendMessage({ action: "reconnect" });
    await new Promise((r) => setTimeout(r, 500));
    await updateStatus();
    flash(btn, t("sent"), true);
  } catch (e) {
    flash(btn, t("failed"), false);
  }
});

$("copy-url-btn").addEventListener("click", async () => {
  const btn = $("copy-url-btn");
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab && tab.url) {
      await navigator.clipboard.writeText(tab.url);
      flash(btn, t("copied"), true);
    } else {
      flash(btn, t("no_url"), false);
    }
  } catch (e) {
    flash(btn, t("copy_fail"), false);
  }
});

$("reload-tab-btn").addEventListener("click", async () => {
  const btn = $("reload-tab-btn");
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab) {
      await chrome.tabs.reload(tab.id);
      flash(btn, t("reloaded"), true);
    }
  } catch (e) {
    flash(btn, t("failed"), false);
  }
});

$("guide-btn").addEventListener("click", () => {
  chrome.tabs.create({ url: chrome.runtime.getURL("install.html") });
});

AemyosI18n.loadSaved();
paintUi();
updateStatus();
setInterval(updateStatus, 2000);
