(function (global) {
  const LANGS = ["en", "tr", "es", "de", "fr"];
  const LABELS = { en: "EN", tr: "TR", es: "ES", de: "DE", fr: "FR" };
  const STRINGS = {
    en: {
      title: "Aemyos Bridge",
      subtitle: "Load this unpacked folder in Chrome, then Aemyos can read and control your own tabs.",
      agent: "Aemyos agent",
      tab: "Tab",
      url: "URL",
      bridge: "Extension bridge",
      connected: "Connected",
      offline: "Offline",
      disconnected: "Disconnected",
      error: "Error",
      sw_error: "Service worker error",
      recent: "Recent commands",
      no_cmds: "No commands yet",
      reconnect: "Reconnect",
      test: "Test page",
      copy_url: "Copy tab URL",
      reload: "Reload tab",
      guide: "Open install guide",
      foot: "Local only · ws://localhost:8769",
      testing: "Testing…",
      internal: "Internal page",
      page_ok: "Page OK",
      script_err: "Script error",
      failed: "Failed",
      connecting: "Connecting…",
      sent: "Sent",
      copied: "Copied",
      no_url: "No URL",
      copy_fail: "Copy failed",
      reloaded: "Reloaded",
      fail: "FAIL",
      unknown: "Unknown",
      bridge_name: "Desktop Agent Bridge",
      agent_off_err: "Cannot reach Aemyos. Is the agent running?",
      s1t: "Open Chrome Extensions",
      s1p: "In the address bar open chrome://extensions. Chrome blocks that link from this page, so copy it or use the installer script.",
      copyExt: "Copy chrome://extensions",
      copyFolder: "Copy folder path",
      s2t: "Enable Developer mode",
      s2p: "Turn on the Developer mode switch at the top-right of the extensions page.",
      s3t: "Load unpacked → this folder",
      s3p: "Click Load unpacked, paste the path below, and select this folder.",
      clickCopy: "Click to copy",
      s4t: "Confirm the connection",
      s4p: "Start Aemyos first. Pin the Aemyos icon. The toolbar badge shows ON when the agent is reachable. If it says Offline, open the popup and press Reconnect.",
      doneT: "After install",
      doneP: "Reload the extension on chrome://extensions after updates. Restart Aemyos if live status stays stuck. No login required — local WebSocket only.",
      checking: "Checking…",
      agentOn: "Online",
      agentOff: "Offline — start Aemyos",
      extOn: "Connected to agent",
      extOff: "Not connected yet",
      extHere: "This page is the loaded extension",
      loadedHint: "chrome-extension / already loaded — use Reload after updates",
      hint: "v1.3.2 · ws://localhost:8769 · local only"
    },
    tr: {
      title: "Aemyos Köprü",
      subtitle: "Bu klasörü Chrome’a paketlenmemiş uzantı olarak yükleyin. Aemyos kendi sekmelerinizi okuyup yönetebilir.",
      agent: "Aemyos ajanı",
      tab: "Sekme",
      url: "URL",
      bridge: "Uzantı köprüsü",
      connected: "Bağlı",
      offline: "Kapalı",
      disconnected: "Bağlı değil",
      error: "Hata",
      sw_error: "Servis işçisi hatası",
      recent: "Son komutlar",
      no_cmds: "Henüz komut yok",
      reconnect: "Yeniden bağlan",
      test: "Sayfayı dene",
      copy_url: "Sekme URL’sini kopyala",
      reload: "Sekmeyi yenile",
      guide: "Kurulum rehberini aç",
      foot: "Yalnızca yerel · ws://localhost:8769",
      testing: "Deneniyor…",
      internal: "Dahili sayfa",
      page_ok: "Sayfa tamam",
      script_err: "Betik hatası",
      failed: "Başarısız",
      connecting: "Bağlanıyor…",
      sent: "Gönderildi",
      copied: "Kopyalandı",
      no_url: "URL yok",
      copy_fail: "Kopyalanamadı",
      reloaded: "Yenilendi",
      fail: "HATA",
      unknown: "Bilinmiyor",
      bridge_name: "Masaüstü ajan köprüsü",
      agent_off_err: "Aemyos’ye ulaşılamıyor. Ajan çalışıyor mu?",
      s1t: "Chrome Uzantılar sayfasını açın",
      s1p: "Adres çubuğuna chrome://extensions yazın. Chrome bu sayfadan o adresi açmayı engeller; kopyalayın veya kurulum betiğini kullanın.",
      copyExt: "chrome://extensions kopyala",
      copyFolder: "Klasör yolunu kopyala",
      s2t: "Geliştirici modunu açın",
      s2p: "Uzantılar sayfasının sağ üstündeki Geliştirici modu anahtarını açın.",
      s3t: "Paketlenmemiş öğe yükle → bu klasör",
      s3p: "Paketlenmemiş öğe yükle’ye tıklayın, aşağıdaki yolu yapıştırın ve bu klasörü seçin.",
      clickCopy: "Kopyalamak için tıklayın",
      s4t: "Bağlantıyı doğrulayın",
      s4p: "Önce Aemyos’yi başlatın. Aemyos simgesini sabitleyin. Ajan açıksa araç çubuğu ON gösterir. Offline ise popup’tan Yeniden bağlan’a basın.",
      doneT: "Kurulumdan sonra",
      doneP: "Güncellemeden sonra chrome://extensions üzerinde uzantıyı yenileyin. Canlı durum takılırsa Aemyos’yi yeniden başlatın. Giriş gerekmez — yalnızca yerel WebSocket.",
      checking: "Kontrol…",
      agentOn: "Çevrimiçi",
      agentOff: "Kapalı — Aemyos’yi başlatın",
      extOn: "Ajana bağlı",
      extOff: "Henüz bağlı değil",
      extHere: "Bu sayfa yüklü uzantıdan açık",
      loadedHint: "chrome-extension / zaten yüklü — güncellemeden sonra Reload",
      hint: "v1.3.2 · ws://localhost:8769 · yalnızca yerel"
    },
    es: {
      title: "Puente Aemyos",
      subtitle: "Carga esta carpeta sin empaquetar en Chrome. Aemyos podrá leer y controlar tus propias pestañas.",
      agent: "Agente Aemyos",
      tab: "Pestaña",
      url: "URL",
      bridge: "Puente de la extensión",
      connected: "Conectado",
      offline: "Sin conexión",
      disconnected: "Desconectado",
      error: "Error",
      sw_error: "Error del service worker",
      recent: "Comandos recientes",
      no_cmds: "Aún no hay comandos",
      reconnect: "Reconectar",
      test: "Probar página",
      copy_url: "Copiar URL",
      reload: "Recargar pestaña",
      guide: "Abrir guía de instalación",
      foot: "Solo local · ws://localhost:8769",
      testing: "Probando…",
      internal: "Página interna",
      page_ok: "Página OK",
      script_err: "Error de script",
      failed: "Falló",
      connecting: "Conectando…",
      sent: "Enviado",
      copied: "Copiado",
      no_url: "Sin URL",
      copy_fail: "No se pudo copiar",
      reloaded: "Recargada",
      fail: "FALLO",
      unknown: "Desconocido",
      bridge_name: "Puente del agente de escritorio",
      agent_off_err: "No se alcanza Aemyos. ¿Está el agente en marcha?",
      s1t: "Abre las extensiones de Chrome",
      s1p: "En la barra de direcciones abre chrome://extensions. Chrome bloquea ese enlace desde esta página; cópialo o usa el instalador.",
      copyExt: "Copiar chrome://extensions",
      copyFolder: "Copiar ruta de la carpeta",
      s2t: "Activa el modo de desarrollador",
      s2p: "Activa el interruptor Modo de desarrollador arriba a la derecha.",
      s3t: "Cargar descomprimida → esta carpeta",
      s3p: "Pulsa Cargar descomprimida, pega la ruta de abajo y elige esta carpeta.",
      clickCopy: "Clic para copiar",
      s4t: "Confirma la conexión",
      s4p: "Arranca Aemyos primero. Fija el icono. El distintivo muestra ON cuando el agente responde. Si pone Offline, abre el popup y pulsa Reconectar.",
      doneT: "Después de instalar",
      doneP: "Recarga la extensión en chrome://extensions tras actualizar. Reinicia Aemyos si el estado se queda atascado. No hay inicio de sesión: solo WebSocket local.",
      checking: "Comprobando…",
      agentOn: "En línea",
      agentOff: "Sin conexión — inicia Aemyos",
      extOn: "Conectado al agente",
      extOff: "Aún no conectado",
      extHere: "Esta página es la extensión cargada",
      loadedHint: "chrome-extension / ya cargada — usa Recargar tras actualizar",
      hint: "v1.3.2 · ws://localhost:8769 · solo local"
    },
    de: {
      title: "Aemyos-Brücke",
      subtitle: "Lade diesen Ordner in Chrome als entpackte Erweiterung. Aemyos kann dann deine eigenen Tabs lesen und steuern.",
      agent: "Aemyos-Agent",
      tab: "Tab",
      url: "URL",
      bridge: "Erweiterungsbrücke",
      connected: "Verbunden",
      offline: "Offline",
      disconnected: "Getrennt",
      error: "Fehler",
      sw_error: "Service-Worker-Fehler",
      recent: "Letzte Befehle",
      no_cmds: "Noch keine Befehle",
      reconnect: "Neu verbinden",
      test: "Seite testen",
      copy_url: "Tab-URL kopieren",
      reload: "Tab neu laden",
      guide: "Installationsanleitung öffnen",
      foot: "Nur lokal · ws://localhost:8769",
      testing: "Teste…",
      internal: "Interne Seite",
      page_ok: "Seite OK",
      script_err: "Skriptfehler",
      failed: "Fehlgeschlagen",
      connecting: "Verbinde…",
      sent: "Gesendet",
      copied: "Kopiert",
      no_url: "Keine URL",
      copy_fail: "Kopieren fehlgeschlagen",
      reloaded: "Neu geladen",
      fail: "FEHLER",
      unknown: "Unbekannt",
      bridge_name: "Desktop-Agent-Brücke",
      agent_off_err: "Aemyos nicht erreichbar. Läuft der Agent?",
      s1t: "Chrome-Erweiterungen öffnen",
      s1p: "Öffne in der Adressleiste chrome://extensions. Chrome blockiert den Link von dieser Seite; kopiere ihn oder nutze das Installer-Skript.",
      copyExt: "chrome://extensions kopieren",
      copyFolder: "Ordnerpfad kopieren",
      s2t: "Entwicklermodus einschalten",
      s2p: "Schalte oben rechts den Schalter Entwicklermodus ein.",
      s3t: "Entpackt laden → dieser Ordner",
      s3p: "Klicke auf Entpackt laden, füge den Pfad unten ein und wähle diesen Ordner.",
      clickCopy: "Zum Kopieren klicken",
      s4t: "Verbindung prüfen",
      s4p: "Starte zuerst Aemyos. Hefte das Symbol an. Das Badge zeigt ON, wenn der Agent erreichbar ist. Steht Offline, öffne das Popup und drücke Neu verbinden.",
      doneT: "Nach der Installation",
      doneP: "Lade die Erweiterung nach Updates auf chrome://extensions neu. Starte Aemyos neu, wenn der Status hängen bleibt. Kein Login — nur lokaler WebSocket.",
      checking: "Prüfe…",
      agentOn: "Online",
      agentOff: "Offline — Aemyos starten",
      extOn: "Mit Agent verbunden",
      extOff: "Noch nicht verbunden",
      extHere: "Diese Seite kommt aus der geladenen Erweiterung",
      loadedHint: "chrome-extension / bereits geladen — nach Updates neu laden",
      hint: "v1.3.2 · ws://localhost:8769 · nur lokal"
    },
    fr: {
      title: "Pont Aemyos",
      subtitle: "Chargez ce dossier non empaqueté dans Chrome. Aemyos pourra alors lire et contrôler vos propres onglets.",
      agent: "Agent Aemyos",
      tab: "Onglet",
      url: "URL",
      bridge: "Pont de l’extension",
      connected: "Connecté",
      offline: "Hors ligne",
      disconnected: "Déconnecté",
      error: "Erreur",
      sw_error: "Erreur du service worker",
      recent: "Commandes récentes",
      no_cmds: "Aucune commande",
      reconnect: "Reconnecter",
      test: "Tester la page",
      copy_url: "Copier l’URL",
      reload: "Recharger l’onglet",
      guide: "Ouvrir le guide d’installation",
      foot: "Local uniquement · ws://localhost:8769",
      testing: "Test…",
      internal: "Page interne",
      page_ok: "Page OK",
      script_err: "Erreur de script",
      failed: "Échec",
      connecting: "Connexion…",
      sent: "Envoyé",
      copied: "Copié",
      no_url: "Pas d’URL",
      copy_fail: "Copie impossible",
      reloaded: "Rechargé",
      fail: "ÉCHEC",
      unknown: "Inconnu",
      bridge_name: "Pont de l’agent bureau",
      agent_off_err: "Aemyos injoignable. L’agent est-il lancé ?",
      s1t: "Ouvrir les extensions Chrome",
      s1p: "Dans la barre d’adresse, ouvrez chrome://extensions. Chrome bloque ce lien depuis cette page ; copiez-le ou utilisez le script d’installation.",
      copyExt: "Copier chrome://extensions",
      copyFolder: "Copier le chemin du dossier",
      s2t: "Activer le mode développeur",
      s2p: "Activez le commutateur Mode développeur en haut à droite.",
      s3t: "Charger non empaquetée → ce dossier",
      s3p: "Cliquez sur Charger l’extension non empaquetée, collez le chemin ci-dessous et choisissez ce dossier.",
      clickCopy: "Cliquer pour copier",
      s4t: "Confirmer la connexion",
      s4p: "Lancez d’abord Aemyos. Épinglez l’icône. Le badge affiche ON quand l’agent répond. Si c’est Hors ligne, ouvrez le popup et appuyez sur Reconnecter.",
      doneT: "Après l’installation",
      doneP: "Rechargez l’extension sur chrome://extensions après une mise à jour. Relancez Aemyos si le statut reste bloqué. Pas de connexion — WebSocket local seulement.",
      checking: "Vérification…",
      agentOn: "En ligne",
      agentOff: "Hors ligne — lancez Aemyos",
      extOn: "Connecté à l’agent",
      extOff: "Pas encore connecté",
      extHere: "Cette page vient de l’extension chargée",
      loadedHint: "chrome-extension / déjà chargée — recharger après une mise à jour",
      hint: "v1.3.2 · ws://localhost:8769 · local uniquement"
    }
  };

  function normalizeLang(code) {
    if (!code) return "en";
    const short = String(code).toLowerCase().replace("_", "-").split("-")[0];
    return LANGS.indexOf(short) >= 0 ? short : "en";
  }

  function detectLang() {
    try {
      const ui = (typeof chrome !== "undefined" && chrome.i18n && chrome.i18n.getUILanguage)
        ? chrome.i18n.getUILanguage() : "";
      const nav = (typeof navigator !== "undefined" && (navigator.language || navigator.userLanguage)) || "";
      return normalizeLang(ui || nav || "en");
    } catch (e) {
      return "en";
    }
  }

  let current = "en";
  let manual = false;

  function t(key) {
    return (STRINGS[current] && STRINGS[current][key]) || STRINGS.en[key] || key;
  }

  function setLang(code) {
    current = normalizeLang(code);
    return current;
  }

  function apply(root) {
    const doc = root || (typeof document !== "undefined" ? document : null);
    if (!doc) return;
    if (doc.documentElement) doc.documentElement.lang = current;
    doc.querySelectorAll("[data-i18n]").forEach((el) => {
      el.textContent = t(el.getAttribute("data-i18n"));
    });
  }

  function readStore() {
    try {
      const saved = localStorage.getItem("aemyos_lang") || localStorage.getItem("davi_lang");
      const flag = localStorage.getItem("aemyos_lang_manual");
      return { lang: saved, manual: flag === "1" };
    } catch (e) {
      return { lang: "", manual: false };
    }
  }

  function loadSaved() {
    const store = readStore();
    manual = !!store.manual;
    if (store.lang) setLang(store.lang);
    else setLang(detectLang());
    return { lang: current, manual: manual };
  }

  function saveLang(code, isManual) {
    setLang(code);
    manual = !!isManual;
    try {
      localStorage.setItem("aemyos_lang", current);
      localStorage.setItem("davi_lang", current);
      localStorage.setItem("aemyos_lang_manual", manual ? "1" : "0");
    } catch (e) {}
    return current;
  }

  function followAgent(code) {
    if (manual) return current;
    if (!code) return current;
    return saveLang(code, false);
  }

  function paintLangButtons(wrap) {
    if (!wrap) return;
    wrap.innerHTML = "";
    LANGS.forEach((code) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.setAttribute("data-lang", code);
      btn.textContent = LABELS[code];
      if (code === current) btn.classList.add("active");
      btn.onclick = () => {
        saveLang(code, true);
        if (typeof wrap.onLangChange === "function") wrap.onLangChange(current);
      };
      wrap.appendChild(btn);
    });
  }

  global.AemyosI18n = {
    LANGS: LANGS,
    LABELS: LABELS,
    t: t,
    setLang: setLang,
    apply: apply,
    loadSaved: loadSaved,
    saveLang: saveLang,
    followAgent: followAgent,
    paintLangButtons: paintLangButtons,
    detectLang: detectLang,
    normalizeLang: normalizeLang,
    get lang() { return current; },
    get manual() { return manual; }
  };
})(typeof window !== "undefined" ? window : self);
