
// ON-AIR Meeting Trigger - simplified (MV3 module)

const DEFAULTS = {
  services: { meet: true, teams: true, zoom: true },
  triggerMode: "ANY_TAB", // or ACTIVE_TAB
  listenerUrl: "",
  direct: { enabled: false, ledBase: "", timeoutSec: 3, verifyStatus: false }
};

const URL_PREFIXES = {
  meet: ["https://meet.google.com/"],
  teams: ["https://teams.microsoft.com/"],
  zoom: ["https://zoom.us/", "https://app.zoom.us/"]
};

const ICONS_COLOR = {
  16: "icons/icon16.png",
  32: "icons/icon32.png",
  48: "icons/icon48.png",
  128: "icons/icon128.png"
};
const ICONS_GRAY = {
  16: "icons/icon16_gray.png",
  32: "icons/icon32_gray.png",
  48: "icons/icon48_gray.png",
  128: "icons/icon128_gray.png"
};

let current = { state: "OFF", service: null, url: null, ts: Date.now() };
let debounceTimer = null;

async function getConfig() {
  const { config } = await chrome.storage.sync.get({ config: DEFAULTS });
  const cfg = { ...DEFAULTS, ...config };
  cfg.services = { ...DEFAULTS.services, ...(config?.services || {}) };
  cfg.direct = { ...DEFAULTS.direct, ...(config?.direct || {}) };
  cfg.direct.ledBase = (cfg.direct.ledBase || "").replace(/\/+$/, "");
  return cfg;
}

function matchService(url, cfg) {
  if (!url) return null;
  for (const [svc, prefixes] of Object.entries(URL_PREFIXES)) {
    if (!cfg.services[svc]) continue;
    if (prefixes.some(p => url.startsWith(p))) return svc;
  }
  return null;
}

async function computeState(cfg) {
  if (cfg.triggerMode === "ACTIVE_TAB") {
    const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    const t = tabs[0] || null;
    const svc = matchService(t?.url || "", cfg);
    return svc ? { state: "ON", service: svc, url: t.url } : { state: "OFF", service: null, url: null };
  }

  const tabs = await chrome.tabs.query({});
  for (const t of tabs) {
    const svc = matchService(t.url || "", cfg);
    if (svc) return { state: "ON", service: svc, url: t.url || null };
  }
  return { state: "OFF", service: null, url: null };
}

function sameState(a, b) {
  return a.state === b.state && a.service === b.service;
}

async function callUrl(url, timeoutSec) {
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), Math.max(1, timeoutSec) * 1000);
  try {
    const r = await fetch(url, { method: "GET", cache: "no-store", signal: ac.signal });
    return { ok: r.ok, status: r.status };
  } finally {
    clearTimeout(t);
  }
}

async function getLedStatus(cfg) {
  if (!cfg.direct.ledBase) return null;
  try {
    const r = await callUrl(cfg.direct.ledBase + "/led/status", cfg.direct.timeoutSec);
    return r.ok ? "REACHABLE" : "UNREACHABLE";
  } catch {
    return "UNREACHABLE";
  }
}

async function setToolbarIcon(state) {
  try {
    await chrome.action.setIcon({ path: state === "OFF" ? ICONS_GRAY : ICONS_COLOR });
  } catch {
    // ignore
  }
}

async function notifyListener(next, cfg) {
  if (!cfg.listenerUrl) return;
  try {
    const u = new URL(cfg.listenerUrl);
    u.searchParams.set("state", next.state);
    if (next.service) u.searchParams.set("service", next.service);
    if (next.url) u.searchParams.set("url", next.url);
    u.searchParams.set("ts", String(Date.now()));
    await callUrl(u.toString(), cfg.direct.timeoutSec);
  } catch {
    // ignore
  }
}

async function ledOn(cfg) {
  if (!cfg.direct.enabled || !cfg.direct.ledBase) return;
  if (cfg.direct.verifyStatus) {
    const st = await getLedStatus(cfg);
    if (st !== "REACHABLE") return;
  }
  await callUrl(cfg.direct.ledBase + "/led/on", cfg.direct.timeoutSec).catch(()=>{});
}

async function ledOff(cfg) {
  if (!cfg.direct.enabled || !cfg.direct.ledBase) return;
  if (cfg.direct.verifyStatus) {
    const st = await getLedStatus(cfg);
    if (st !== "REACHABLE") return;
  }
  await callUrl(cfg.direct.ledBase + "/led/off", cfg.direct.timeoutSec).catch(()=>{});
}

async function applySideEffects(next, cfg) {
  await setToolbarIcon(next.state);
  await notifyListener(next, cfg);

  if (next.state === "ON") await ledOn(cfg);
  else await ledOff(cfg);
}

async function tick(reason="") {
  const cfg = await getConfig();
  const next = await computeState(cfg);

  if (sameState(next, current)) {
    // Ensure icon is correct after SW wake
    await setToolbarIcon(next.state);
    current = { ...next, ts: Date.now() };
    return;
  }

  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(async () => {
    const cfg2 = await getConfig();
    const next2 = await computeState(cfg2);
    current = { ...next2, ts: Date.now() };
    await applySideEffects(current, cfg2);
  }, 400);
}

// Tab/window events
chrome.tabs.onCreated.addListener(() => tick("created"));
chrome.tabs.onUpdated.addListener(() => tick("updated"));
chrome.tabs.onRemoved.addListener(() => tick("removed"));
chrome.tabs.onActivated.addListener(() => tick("activated"));
chrome.windows.onFocusChanged.addListener(() => tick("focus"));

chrome.runtime.onStartup.addListener(() => tick("startup"));
chrome.runtime.onInstalled.addListener(() => tick("installed"));

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    if (msg?.type === "GET_STATE") {
      sendResponse({ state: current.state, service: current.service });
      return;
    }
    if (msg?.type === "CONFIG_UPDATED") {
      await tick("config");
      sendResponse({ ok: true });
      return;
    }
    sendResponse({ ok: false });
  })();
  return true;
});
