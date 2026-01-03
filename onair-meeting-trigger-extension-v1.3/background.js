// ON-AIR Meeting Trigger — universal targets (MV3 module)
//
// Adds "targets" so you can drive any IoT device via HTTP hooks (e.g., Tasmota),
// while keeping legacy listenerUrl + direct LED support.

const LEGACY_DEFAULTS = {
  services: { meet: true, teams: true, zoom: true },
  triggerMode: "ANY_TAB", // or ACTIVE_TAB
  listenerUrl: "",
  direct: { enabled: false, ledBase: "", timeoutSec: 3, verifyStatus: false }
};

// New defaults
const DEFAULTS = {
  services: { meet: true, teams: true, zoom: true },
  triggerMode: "ANY_TAB",
  timeoutSec: 3,
  targets: [
    // Examples:
    // { id:"listener1", type:"listener", enabled:false, url:"http://127.0.0.1:8765/event?state={state}&service={service}&url={url}&ts={ts}" },
    // { id:"tasmota1", type:"httpHook", enabled:false, onUrl:"http://192.168.1.17/cm?cmnd=Power%20On", offUrl:"http://192.168.1.17/cm?cmnd=Power%20Off", method:"GET", headers:[], body:"" },
    // { id:"led1", type:"simpleLed", enabled:false, baseUrl:"http://192.168.1.50", verifyStatus:false }
  ]
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

function trimSlash(s) {
  return (s || "").replace(/\/+$/, "");
}

function newId(prefix="t") {
  return `${prefix}_${Math.random().toString(16).slice(2, 10)}`;
}

function normalizeHeaders(headers) {
  if (!Array.isArray(headers)) return [];
  return headers
    .filter(h => h && typeof h.key === "string" && h.key.trim() !== "")
    .map(h => ({ key: h.key.trim(), value: String(h.value ?? "") }));
}

// Legacy -> targets migration (best-effort)
function migrateConfig(config) {
  // If already on new schema, just normalize a bit
  if (config?.targets && Array.isArray(config.targets)) {
    const cfg = { ...DEFAULTS, ...config };
    cfg.services = { ...DEFAULTS.services, ...(config?.services || {}) };
    cfg.timeoutSec = Math.max(1, Math.min(20, parseInt(cfg.timeoutSec ?? 3, 10)));

    cfg.targets = cfg.targets.map(t => {
      const tt = { ...t };
      tt.enabled = !!tt.enabled;
      if (!tt.id) tt.id = newId(tt.type || "t");
      if (tt.type === "simpleLed") {
        tt.baseUrl = trimSlash(tt.baseUrl || "");
        tt.verifyStatus = !!tt.verifyStatus;
      }
      if (tt.type === "listener") {
        tt.url = (tt.url || "").trim();
      }
      if (tt.type === "httpHook") {
        tt.onUrl = (tt.onUrl || "").trim();
        tt.offUrl = (tt.offUrl || "").trim();
        tt.method = (tt.method || "GET").toUpperCase();
        tt.headers = normalizeHeaders(tt.headers);
        tt.body = String(tt.body ?? "");
        tt.basicAuth = tt.basicAuth
          ? { user: String(tt.basicAuth.user ?? ""), pass: String(tt.basicAuth.pass ?? "") }
          : null;
      }
      return tt;
    });

    return cfg;
  }

  // Otherwise: treat it as legacy and convert
  const legacy = { ...LEGACY_DEFAULTS, ...(config || {}) };
  legacy.services = { ...LEGACY_DEFAULTS.services, ...(config?.services || {}) };
  legacy.direct = { ...LEGACY_DEFAULTS.direct, ...(config?.direct || {}) };

  const targets = [];

  if (legacy.listenerUrl && legacy.listenerUrl.trim()) {
    // Convert to templated URL (match your old behavior but more explicit)
    const base = legacy.listenerUrl.trim();
    // If user already put query params, keep them; append in execution if it has no {state} token.
    targets.push({
      id: newId("listener"),
      type: "listener",
      enabled: true,
      url: base
    });
  }

  if (legacy.direct?.enabled && legacy.direct?.ledBase) {
    targets.push({
      id: newId("led"),
      type: "simpleLed",
      enabled: true,
      baseUrl: trimSlash(legacy.direct.ledBase),
      verifyStatus: !!legacy.direct.verifyStatus
    });
  }

  return {
    services: legacy.services,
    triggerMode: legacy.triggerMode || "ANY_TAB",
    timeoutSec: Math.max(1, Math.min(20, parseInt(legacy.direct?.timeoutSec ?? 3, 10))),
    targets
  };
}

async function getConfig() {
  const { config } = await chrome.storage.sync.get({ config: DEFAULTS });
  const cfg = migrateConfig(config);

  // Persist migrated config once so options UI sees it
  if (!config?.targets && cfg.targets) {
    await chrome.storage.sync.set({ config: cfg });
  }
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

function applyTemplate(str, vars) {
  return String(str ?? "")
    .replaceAll("{state}", vars.state ?? "")
    .replaceAll("{service}", vars.service ?? "")
    .replaceAll("{url}", vars.url ?? "")
    .replaceAll("{ts}", String(vars.ts ?? ""));
}

async function callUrl(url, timeoutSec, fetchOpts = {}) {
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), Math.max(1, timeoutSec) * 1000);
  try {
    const r = await fetch(url, {
      method: fetchOpts.method || "GET",
      headers: fetchOpts.headers || undefined,
      body: fetchOpts.body || undefined,
      cache: "no-store",
      signal: ac.signal
    });
    return { ok: r.ok, status: r.status };
  } finally {
    clearTimeout(t);
  }
}

async function setToolbarIcon(state) {
  try {
    await chrome.action.setIcon({ path: state === "OFF" ? ICONS_GRAY : ICONS_COLOR });
  } catch {
    // ignore
  }
}

// ---- Target executors ----

async function runListenerTarget(target, vars, timeoutSec) {
  if (!target?.enabled || !target?.url) return;

  // Back-compat: if they used old listener URL without tokens, mimic old behavior:
  // append ?state=...&service=...&url=...&ts=...
  // If they DO use {state} tokens, we don't append anything.
  let finalUrl = target.url.trim();

  if (finalUrl.includes("{state}") || finalUrl.includes("{service}") || finalUrl.includes("{url}") || finalUrl.includes("{ts}")) {
    finalUrl = applyTemplate(finalUrl, vars);
  } else {
    try {
      const u = new URL(finalUrl);
      u.searchParams.set("state", vars.state);
      if (vars.service) u.searchParams.set("service", vars.service);
      if (vars.url) u.searchParams.set("url", vars.url);
      u.searchParams.set("ts", String(vars.ts));
      finalUrl = u.toString();
    } catch {
      // If invalid URL, just skip
      return;
    }
  }

  await callUrl(finalUrl, timeoutSec).catch(() => {});
}

async function getLedStatus(baseUrl, timeoutSec) {
  try {
    const r = await callUrl(baseUrl + "/led/status", timeoutSec);
    return r.ok ? "REACHABLE" : "UNREACHABLE";
  } catch {
    return "UNREACHABLE";
  }
}

async function runSimpleLedTarget(target, vars, timeoutSec) {
  if (!target?.enabled || !target?.baseUrl) return;
  const base = trimSlash(target.baseUrl);

  if (target.verifyStatus) {
    const st = await getLedStatus(base, timeoutSec);
    if (st !== "REACHABLE") return;
  }

  const path = vars.state === "ON" ? "/led/on" : "/led/off";
  await callUrl(base + path, timeoutSec).catch(() => {});
}

function buildAuthHeader(basicAuth) {
  if (!basicAuth || (!basicAuth.user && !basicAuth.pass)) return null;
  const token = btoa(`${basicAuth.user || ""}:${basicAuth.pass || ""}`);
  return `Basic ${token}`;
}

async function runHttpHookTarget(target, vars, timeoutSec) {
  if (!target?.enabled) return;

  const urlTemplate = vars.state === "ON" ? target.onUrl : target.offUrl;
  if (!urlTemplate) return;

  const url = applyTemplate(urlTemplate, vars);
  const method = (target.method || "GET").toUpperCase();

  const headers = new Headers();
  for (const h of normalizeHeaders(target.headers)) headers.set(h.key, h.value);

  const auth = buildAuthHeader(target.basicAuth);
  if (auth) headers.set("Authorization", auth);

  let body = null;
  const bodyTpl = target.body || "";
  if (method !== "GET" && method !== "HEAD") {
    const rendered = applyTemplate(bodyTpl, vars);
    if (rendered.length) body = rendered;
  }

  await callUrl(url, timeoutSec, { method, headers, body }).catch(() => {});
}

async function applySideEffects(next, cfg) {
  await setToolbarIcon(next.state);

  const vars = {
    state: next.state,
    service: next.service || "",
    url: next.url || "",
    ts: Date.now()
  };

  const timeoutSec = Math.max(1, Math.min(20, parseInt(cfg.timeoutSec ?? 3, 10)));

  // Fire all enabled targets (don’t block others if one fails)
  const jobs = [];
  for (const t of cfg.targets || []) {
    if (!t?.enabled) continue;
    if (t.type === "listener") jobs.push(runListenerTarget(t, vars, timeoutSec));
    else if (t.type === "simpleLed") jobs.push(runSimpleLedTarget(t, vars, timeoutSec));
    else if (t.type === "httpHook") jobs.push(runHttpHookTarget(t, vars, timeoutSec));
  }
  await Promise.allSettled(jobs);
}

async function tick(reason = "") {
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
