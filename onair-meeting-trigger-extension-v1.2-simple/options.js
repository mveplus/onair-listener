
const DEFAULTS = {
  services: { meet: true, teams: true, zoom: true },
  triggerMode: "ANY_TAB",
  listenerUrl: "",
  direct: { enabled: false, ledBase: "", timeoutSec: 3, verifyStatus: false }
};

function $(id){ return document.getElementById(id); }

async function load() {
  const { config } = await chrome.storage.sync.get({ config: DEFAULTS });
  const cfg = { ...DEFAULTS, ...config };
  cfg.services = { ...DEFAULTS.services, ...(config?.services || {}) };
  cfg.direct = { ...DEFAULTS.direct, ...(config?.direct || {}) };

  $("svc_meet").checked = !!cfg.services.meet;
  $("svc_teams").checked = !!cfg.services.teams;
  $("svc_zoom").checked = !!cfg.services.zoom;

  $("mode_any").checked = cfg.triggerMode === "ANY_TAB";
  $("mode_active").checked = cfg.triggerMode === "ACTIVE_TAB";

  $("listener_url").value = cfg.listenerUrl || "";

  $("direct_enabled").checked = !!cfg.direct.enabled;
  $("led_base").value = cfg.direct.ledBase || "";
  $("http_timeout").value = cfg.direct.timeoutSec ?? 3;
  $("verify_status").checked = !!cfg.direct.verifyStatus;
}

function showStatus(msg, ok=true) {
  const s = $("status");
  s.textContent = msg;
  s.style.color = ok ? "#0a0" : "#a00";
  setTimeout(()=>{ s.textContent = ""; }, 2500);
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

async function save() {
  const cfg = {
    services: {
      meet: $("svc_meet").checked,
      teams: $("svc_teams").checked,
      zoom: $("svc_zoom").checked
    },
    triggerMode: $("mode_active").checked ? "ACTIVE_TAB" : "ANY_TAB",
    listenerUrl: $("listener_url").value.trim(),
    direct: {
      enabled: $("direct_enabled").checked,
      ledBase: $("led_base").value.trim().replace(/\/+$/, ""),
      timeoutSec: Math.max(1, Math.min(20, parseInt($("http_timeout").value || "3", 10))),
      verifyStatus: $("verify_status").checked
    }
  };

  if (cfg.listenerUrl) {
    const ok = await ensureHostPermissionFor(cfg.listenerUrl);
    if (!ok) return showStatus("Permission denied for listener URL", false);
  }
  if (cfg.direct.enabled && cfg.direct.ledBase) {
    const ok = await ensureHostPermissionFor(cfg.direct.ledBase + "/");
    if (!ok) return showStatus("Permission denied for LED URL", false);
  }

  await chrome.storage.sync.set({ config: cfg });
  showStatus("Saved");
  chrome.runtime.sendMessage({ type: "CONFIG_UPDATED" });
}

async function testDirect(path) {
  const { config } = await chrome.storage.sync.get({ config: DEFAULTS });
  const base = (config?.direct?.ledBase || "").replace(/\/+$/, "");
  if (!base) return showStatus("Set LED base URL first", false);

  const url = base + path;
  try {
    const r = await fetch(url, { method: "GET", cache: "no-store" });
    showStatus(`OK: ${path} (HTTP ${r.status})`, r.ok);
  } catch {
    showStatus(`Failed: ${path}`, false);
  }
}

$("save").addEventListener("click", save);
$("test_on").addEventListener("click", ()=>testDirect("/led/on"));
$("test_off").addEventListener("click", ()=>testDirect("/led/off"));

load();
