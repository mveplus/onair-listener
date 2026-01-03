const DEFAULTS = {
  services: { meet: true, teams: true, zoom: true },
  triggerMode: "ANY_TAB",
  timeoutSec: 3,
  targets: []
};

function $(id){ return document.getElementById(id); }
function esc(s){ return String(s ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;"); }
function trimSlash(s){ return (s || "").replace(/\/+$/, ""); }
function newId(prefix="t"){ return `${prefix}_${Math.random().toString(16).slice(2,10)}`; }

function showStatus(msg, ok=true) {
  const s = $("status");
  s.textContent = msg;
  s.style.color = ok ? "#0a0" : "#a00";
  setTimeout(()=>{ s.textContent = ""; }, 2500);
}

function migrateIfNeeded(config) {
  // If already new schema
  if (config?.targets && Array.isArray(config.targets)) return config;

  // Try to migrate legacy fields if present
  const legacy = config || {};
  const targets = [];

  if (legacy.listenerUrl && legacy.listenerUrl.trim()) {
    targets.push({ id: newId("listener"), type:"listener", enabled:true, url: legacy.listenerUrl.trim() });
  }
  if (legacy.direct?.enabled && legacy.direct?.ledBase) {
    targets.push({
      id: newId("led"),
      type:"simpleLed",
      enabled:true,
      baseUrl: trimSlash(legacy.direct.ledBase),
      verifyStatus: !!legacy.direct.verifyStatus
    });
  }

  return {
    services: { ...DEFAULTS.services, ...(legacy.services || {}) },
    triggerMode: legacy.triggerMode || "ANY_TAB",
    timeoutSec: Math.max(1, Math.min(20, parseInt(legacy.direct?.timeoutSec ?? 3, 10))),
    targets
  };
}

async function ensureHostPermissionFor(url) {
  try {
    const u = new URL(url);
    const originPattern = `${u.protocol}//${u.host}/*`;
    return await chrome.permissions.request({ origins: [originPattern] });
  } catch {
    return false;
  }
}

function getOriginsFromTargets(cfg) {
  const urls = [];
  for (const t of cfg.targets || []) {
    if (!t.enabled) continue;
    if (t.type === "listener" && t.url) urls.push(t.url);
    if (t.type === "simpleLed" && t.baseUrl) urls.push(t.baseUrl + "/");
    if (t.type === "httpHook") {
      if (t.onUrl) urls.push(t.onUrl);
      if (t.offUrl) urls.push(t.offUrl);
    }
  }
  return urls;
}

function renderTargets(cfg) {
  const wrap = $("targets");
  wrap.innerHTML = "";

  (cfg.targets || []).forEach((t, idx) => {
    const typeLabel = t.type === "listener" ? "Listener"
      : t.type === "simpleLed" ? "Simple LED"
      : "HTTP Hook";

    const div = document.createElement("div");
    div.className = "target";
    div.dataset.id = t.id;

    div.innerHTML = `
      <div class="targetHead">
        <div>
          <b>${esc(typeLabel)}</b>
          <span class="pill">${esc(t.id)}</span>
        </div>
        <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
          <label style="margin:0;"><input type="checkbox" class="t_enabled" ${t.enabled ? "checked":""}> Enabled</label>
          <button class="danger t_remove">Remove</button>
        </div>
      </div>

      <div class="t_body" style="margin-top:10px;"></div>
    `;

    const body = div.querySelector(".t_body");

    if (t.type === "listener") {
      body.innerHTML = `
        <label>URL
          <input type="text" class="t_url" placeholder="http://127.0.0.1:8765/event?state={state}&service={service}&url={url}&ts={ts}" value="${esc(t.url || "")}">
        </label>
        <div class="muted">If you don&#39;t use tokens, the extension will append <code>?state=..&amp;service=..&amp;url=..&amp;ts=..</code> automatically (backward compatible).</div>
      `;
    } else if (t.type === "simpleLed") {
      body.innerHTML = `
        <div class="row">
          <div>
            <label>Base URL
              <input type="text" class="t_baseUrl" placeholder="http://192.168.1.50" value="${esc(t.baseUrl || "")}">
            </label>
            <div class="muted">Uses <code>/led/on</code>, <code>/led/off</code>, optional <code>/led/status</code>.</div>
          </div>
          <div>
            <label style="margin-top:30px;"><input type="checkbox" class="t_verify" ${t.verifyStatus ? "checked":""}> Verify using <code>/led/status</code></label>
          </div>
        </div>
      `;
    } else {
      // httpHook
      body.innerHTML = `
        <div class="row">
          <div>
            <label>ON URL
              <input type="text" class="t_onUrl" placeholder="http://192.168.1.17/cm?cmnd=Power%20On" value="${esc(t.onUrl || "")}">
            </label>
            <label>OFF URL
              <input type="text" class="t_offUrl" placeholder="http://192.168.1.17/cm?cmnd=Power%20Off" value="${esc(t.offUrl || "")}">
            </label>
          </div>
          <div>
            <label>Method
              <select class="t_method">
                ${["GET","POST","PUT"].map(m => `<option value="${m}" ${String(t.method||"GET").toUpperCase()===m?"selected":""}>${m}</option>`).join("")}
              </select>
            </label>
            <label>Basic Auth (optional) user:pass
              <input type="text" class="t_auth" placeholder="admin:secret" value="${esc(t.basicAuth ? `${t.basicAuth.user||""}:${t.basicAuth.pass||""}` : "")}">
            </label>
          </div>
        </div>

        <label>Headers (one per line: <code>Key: Value</code>)</label>
        <textarea class="t_headers" placeholder="Content-Type: text/plain">${esc((t.headers||[]).map(h=>`${h.key}: ${h.value}`).join("\n"))}</textarea>

        <label>Body (optional; tokens allowed)</label>
        <textarea class="t_bodyText" placeholder='{"state":"{state}","service":"{service}"}'>${esc(t.body || "")}</textarea>

        <div class="muted">For Tasmota you usually want <code>GET</code> and empty body/headers.</div>
      `;
    }

    // Wire remove
    div.querySelector(".t_remove").addEventListener("click", () => {
      cfg.targets.splice(idx, 1);
      renderTargets(cfg);
    });

    wrap.appendChild(div);
  });
}

function readTargetsFromUI(cfg) {
  const wrap = $("targets");
  const nodes = [...wrap.querySelectorAll(".target")];

  const out = [];
  for (const n of nodes) {
    const id = n.dataset.id;
    const t = (cfg.targets || []).find(x => x.id === id);
    if (!t) continue;

    const enabled = !!n.querySelector(".t_enabled")?.checked;
    const base = { ...t, enabled };

    if (t.type === "listener") {
      base.url = n.querySelector(".t_url")?.value.trim() || "";
    } else if (t.type === "simpleLed") {
      base.baseUrl = trimSlash(n.querySelector(".t_baseUrl")?.value.trim() || "");
      base.verifyStatus = !!n.querySelector(".t_verify")?.checked;
    } else {
      base.onUrl = n.querySelector(".t_onUrl")?.value.trim() || "";
      base.offUrl = n.querySelector(".t_offUrl")?.value.trim() || "";
      base.method = (n.querySelector(".t_method")?.value || "GET").toUpperCase();

      const auth = (n.querySelector(".t_auth")?.value || "").trim();
      if (auth.includes(":")) {
        const [user, ...rest] = auth.split(":");
        base.basicAuth = { user: user || "", pass: rest.join(":") || "" };
      } else {
        base.basicAuth = null;
      }

      // Headers
      const headersRaw = (n.querySelector(".t_headers")?.value || "").split("\n");
      base.headers = headersRaw
        .map(line => line.trim())
        .filter(Boolean)
        .map(line => {
          const i = line.indexOf(":");
          if (i < 1) return null;
          return { key: line.slice(0, i).trim(), value: line.slice(i+1).trim() };
        })
        .filter(Boolean);

      base.body = n.querySelector(".t_bodyText")?.value ?? "";
    }

    out.push(base);
  }

  cfg.targets = out;
  return cfg;
}

async function load() {
  const { config } = await chrome.storage.sync.get({ config: DEFAULTS });
  const cfg = migrateIfNeeded(config);

  $("svc_meet").checked = !!cfg.services.meet;
  $("svc_teams").checked = !!cfg.services.teams;
  $("svc_zoom").checked = !!cfg.services.zoom;

  $("mode_any").checked = cfg.triggerMode === "ANY_TAB";
  $("mode_active").checked = cfg.triggerMode === "ACTIVE_TAB";

  $("http_timeout").value = cfg.timeoutSec ?? 3;

  // Store current cfg on window for edits
  window.__cfg = cfg;
  renderTargets(cfg);
}

function addTarget(type) {
  const cfg = window.__cfg;
  if (!cfg.targets) cfg.targets = [];

  if (type === "listener") {
    cfg.targets.push({
      id: newId("listener"),
      type: "listener",
      enabled: true,
      url: "http://127.0.0.1:8765/event?state={state}&service={service}&url={url}&ts={ts}"
    });
  } else if (type === "simpleLed") {
    cfg.targets.push({
      id: newId("led"),
      type: "simpleLed",
      enabled: true,
      baseUrl: "",
      verifyStatus: false
    });
  } else {
    // httpHook, pre-fill for Tasmota
    cfg.targets.push({
      id: newId("hook"),
      type: "httpHook",
      enabled: true,
      onUrl: "http://192.168.1.17/cm?cmnd=Power%20On",
      offUrl: "http://192.168.1.17/cm?cmnd=Power%20Off",
      method: "GET",
      headers: [],
      body: "",
      basicAuth: null
    });
  }
  renderTargets(cfg);
}

async function save() {
  let cfg = window.__cfg;

  cfg = {
    services: {
      meet: $("svc_meet").checked,
      teams: $("svc_teams").checked,
      zoom: $("svc_zoom").checked
    },
    triggerMode: $("mode_active").checked ? "ACTIVE_TAB" : "ANY_TAB",
    timeoutSec: Math.max(1, Math.min(20, parseInt($("http_timeout").value || "3", 10))),
    targets: cfg.targets || []
  };

  cfg = readTargetsFromUI(cfg);

  // Request permissions for all enabled target origins
  for (const url of getOriginsFromTargets(cfg)) {
    const ok = await ensureHostPermissionFor(url);
    if (!ok) return showStatus(`Permission denied for ${url}`, false);
  }

  await chrome.storage.sync.set({ config: cfg });
  showStatus("Saved");
  chrome.runtime.sendMessage({ type: "CONFIG_UPDATED" });
}

function applyTemplate(str, vars) {
  return String(str ?? "")
    .replaceAll("{state}", vars.state ?? "")
    .replaceAll("{service}", vars.service ?? "")
    .replaceAll("{url}", vars.url ?? "")
    .replaceAll("{ts}", String(vars.ts ?? ""));
}

function btoaSafe(s) {
  try { return btoa(s); } catch { return ""; }
}

async function testAll(state) {
  const { config } = await chrome.storage.sync.get({ config: DEFAULTS });
  const cfg = migrateIfNeeded(config);

  const vars = { state, service: "test", url: "", ts: Date.now() };
  const timeoutMs = Math.max(1, Math.min(20, parseInt(cfg.timeoutSec ?? 3, 10))) * 1000;

  const jobs = (cfg.targets || []).filter(t => t.enabled).map(async (t) => {
    if (t.type === "listener") {
      let url = t.url || "";
      if (url.includes("{state}") || url.includes("{service}") || url.includes("{url}") || url.includes("{ts}")) {
        url = applyTemplate(url, vars);
      } else {
        try {
          const u = new URL(url);
          u.searchParams.set("state", vars.state);
          u.searchParams.set("service", vars.service);
          u.searchParams.set("ts", String(vars.ts));
          url = u.toString();
        } catch {
          return { ok:false, name:t.id };
        }
      }
      return fetchWithTimeout(url, { method:"GET" }, timeoutMs).then(ok => ({ ok, name:t.id }));
    }

    if (t.type === "simpleLed") {
      const base = trimSlash(t.baseUrl || "");
      if (!base) return { ok:false, name:t.id };
      const url = base + (state === "ON" ? "/led/on" : "/led/off");
      return fetchWithTimeout(url, { method:"GET" }, timeoutMs).then(ok => ({ ok, name:t.id }));
    }

    // httpHook
    const urlTpl = state === "ON" ? t.onUrl : t.offUrl;
    if (!urlTpl) return { ok:false, name:t.id };
    const url = applyTemplate(urlTpl, vars);
    const method = (t.method || "GET").toUpperCase();

    const headers = new Headers();
    for (const h of (t.headers || [])) headers.set(h.key, h.value);

    if (t.basicAuth && (t.basicAuth.user || t.basicAuth.pass)) {
      headers.set("Authorization", "Basic " + btoaSafe(`${t.basicAuth.user||""}:${t.basicAuth.pass||""}`));
    }

    const body = (method === "GET" || method === "HEAD") ? undefined : (applyTemplate(t.body || "", vars) || undefined);

    return fetchWithTimeout(url, { method, headers, body }, timeoutMs).then(ok => ({ ok, name:t.id }));
  });

  const res = await Promise.allSettled(jobs);
  const okCount = res.filter(r => r.status === "fulfilled" && r.value.ok).length;
  const total = res.length;
  showStatus(`Test ${state}: ${okCount}/${total} OK`, okCount === total);
}

async function fetchWithTimeout(url, opts, timeoutMs) {
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), timeoutMs);
  try {
    const r = await fetch(url, { ...opts, cache:"no-store", signal: ac.signal });
    return r.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(t);
  }
}

$("save").addEventListener("click", save);
$("test_on").addEventListener("click", () => testAll("ON"));
$("test_off").addEventListener("click", () => testAll("OFF"));

$("add_listener").addEventListener("click", () => addTarget("listener"));
$("add_led").addEventListener("click", () => addTarget("simpleLed"));
$("add_hook").addEventListener("click", () => addTarget("httpHook"));

load();
