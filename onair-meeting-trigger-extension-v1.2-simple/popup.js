
function $(id){ return document.getElementById(id); }

async function refresh() {
  const resp = await chrome.runtime.sendMessage({ type: "GET_STATE" });
  const st = resp?.state || "OFF";
  const svc = resp?.service || "—";

  const stateEl = $("state");
  stateEl.textContent = st;
  stateEl.classList.toggle("on", st === "ON");
  stateEl.classList.toggle("off", st !== "ON");

  $("service").textContent = svc;
}

$("openOptions").addEventListener("click", () => chrome.runtime.openOptionsPage());
$("refresh").addEventListener("click", refresh);
refresh();
