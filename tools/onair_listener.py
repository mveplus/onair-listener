#!/usr/bin/env python3
"""
ON-AIR Listener (combined)

Input:
  Extension sends:
    GET /event?state=ON|OFF&service=meet|teams|zoom&url=...

This listener:
  - Maintains meeting_open state from those events
  - Optionally detects mic/cam (PipeWire + /dev/video via fuser)
  - Applies MODE:
      TAB_ONLY         -> ON if meeting_open
      TAB_AND_ANY_AV   -> ON if meeting_open AND (mic OR cam)
      TAB_AND_BOTH_AV  -> ON if meeting_open AND mic AND cam
  - Drives LED:
      GET /led/on
      GET /led/off

Debug:
  GET /health         -> ok
  GET /debug          -> JSON current state
"""

import argparse
import json
import time
import threading
import subprocess
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

# ---- AV detection helpers ----

VIDEO_DEVICES_DEFAULT = ("/dev/video0", "/dev/video1")

def _pw_dump():
    out = subprocess.check_output(["pw-dump"], text=True)
    return json.loads(out)

def _props(obj):
    return (obj.get("info") or {}).get("props") or obj.get("props") or {}

def mic_in_use(app_hint: str = "chromium") -> bool:
    """
    PipeWire mic capture detection.
    Your system showed: media.class == Stream/Input/Audio, application.name contains 'Chromium input'
    We use a tolerant match (contains app_hint).
    """
    try:
        for o in _pw_dump():
            p = _props(o)
            mc = (p.get("media.class") or "")
            app = (p.get("application.name") or "").lower()
            if mc == "Stream/Input/Audio" and app_hint.lower() in app:
                return True
    except Exception:
        return False
    return False

def camera_in_use(video_devices=VIDEO_DEVICES_DEFAULT) -> bool:
    """
    Camera detection via /dev/video* busy check.
    Uses 'fuser'. Install: Fedora 'psmisc' / Debian 'psmisc'.
    Requires perms on /dev/video* (video group) OR run the listener with sufficient permissions.
    """
    for dev in video_devices:
        try:
            subprocess.check_output(["fuser", dev], stderr=subprocess.DEVNULL)
            return True
        except subprocess.CalledProcessError:
            continue
        except FileNotFoundError:
            return False
    return False

# ---- LED helpers ----

def http_get(url: str, timeout: float) -> int:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.getcode()

def led_call(led_base: str, state: str, timeout: float, retries: int, verbose: bool) -> tuple[bool, str]:
    if not led_base:
        return True, "LED disabled"

    target = "/led/on" if state == "ON" else "/led/off"
    url = led_base.rstrip("/") + target

    last_err = None
    for attempt in range(retries + 1):
        try:
            code = http_get(url, timeout=timeout)
            return True, f"{url} -> HTTP {code}"
        except Exception as e:
            last_err = e
            if attempt < retries:
                sleep_s = [0.2, 0.5, 1.0, 2.0][min(attempt, 3)]
                if verbose:
                    print(f"[{time.ctime()}] LED retry {attempt+1}/{retries} after error: {e} (sleep {sleep_s}s)")
                time.sleep(sleep_s)

    return False, f"LED failed: {last_err}"

# ---- State + policy ----

class SharedState:
    meeting_open = False
    meeting_service = ""
    meeting_url = ""
    last_event_ts = 0.0

    mic = None  # bool
    cam = None  # bool
    desired = "OFF"  # "ON"/"OFF"

    last_led_sent = None
    last_led_ts = 0.0

state_lock = threading.Lock()

def compute_desired(mode: str, meeting_open: bool, mic: bool, cam: bool) -> str:
    if not meeting_open:
        return "OFF"
    if mode == "TAB_ONLY":
        return "ON"
    if mode == "TAB_AND_ANY_AV":
        return "ON" if (mic or cam) else "OFF"
    if mode == "TAB_AND_BOTH_AV":
        return "ON" if (mic and cam) else "OFF"
    return "OFF"

# ---- HTTP server ----

class Handler(BaseHTTPRequestHandler):
    server_version = "onair-listener/2.0"

    def _send(self, code: int, body: str, content_type="text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write((body + "\n").encode("utf-8"))

    def log_message(self, fmt, *args):
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    def do_GET(self):
        u = urlparse(self.path)

        if u.path == "/health":
            self._send(200, "ok")
            return

        if u.path == "/debug":
            with state_lock:
                payload = {
                    "meeting_open": SharedState.meeting_open,
                    "service": SharedState.meeting_service,
                    "url": SharedState.meeting_url,
                    "mic": SharedState.mic,
                    "cam": SharedState.cam,
                    "mode": self.server.mode,
                    "desired": SharedState.desired,
                    "last_led_sent": SharedState.last_led_sent,
                    "last_event_ts": SharedState.last_event_ts,
                }
            self._send(200, json.dumps(payload, indent=2), content_type="application/json; charset=utf-8")
            return

        if u.path not in ("/event", "/"):
            self._send(404, "not found (use /event, /health, /debug)")
            return

        q = parse_qs(u.query)
        ev_state = (q.get("state", [""])[0] or "").upper()
        service = (q.get("service", [""])[0] or "")
        page_url = (q.get("url", [""])[0] or "")

        if self.server.verbose:
            print(f"[{time.ctime()}] EVENT REQ state={ev_state!r} service={service!r} url={page_url[:120]!r}")

        if ev_state not in ("ON", "OFF"):
            self._send(200, "ignored (state must be ON or OFF)")
            return

        with state_lock:
            SharedState.meeting_open = (ev_state == "ON")
            SharedState.meeting_service = service
            SharedState.meeting_url = page_url
            SharedState.last_event_ts = time.time()

        self._send(200, "ok")

# ---- Main loop (poll AV + drive LED) ----

def loop(server: HTTPServer):
    while True:
        time.sleep(server.poll_seconds)

        with state_lock:
            meeting_open = SharedState.meeting_open

        # Optional AV detection
        mic = False
        cam = False
        if server.av_enabled and meeting_open:
            mic = mic_in_use(app_hint=server.mic_app_hint)
            cam = camera_in_use(video_devices=server.video_devices)

        desired = compute_desired(server.mode, meeting_open, mic, cam)

        with state_lock:
            SharedState.mic = mic if (server.av_enabled and meeting_open) else None
            SharedState.cam = cam if (server.av_enabled and meeting_open) else None
            SharedState.desired = desired

            # Debounce + state-change-only LED commands
            now = time.time()
            if SharedState.last_led_sent == desired and (now - SharedState.last_led_ts) < server.debounce_sec:
                continue

            if SharedState.last_led_sent == desired:
                continue

        ok, msg = led_call(
            led_base=server.led_base,
            state=desired,
            timeout=server.led_timeout,
            retries=server.led_retries,
            verbose=server.verbose
        )

        with state_lock:
            SharedState.last_led_sent = desired
            SharedState.last_led_ts = time.time()

        if server.verbose:
            print(f"[{time.ctime()}] LED {desired} | mic={mic} cam={cam} meeting={meeting_open} -> {msg}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", default="127.0.0.1", help="127.0.0.1 local-only, 0.0.0.0 to accept LAN")
    ap.add_argument("--port", type=int, default=8765)

    ap.add_argument("--led", dest="led_base", default="", help="e.g. http://192.168.1.172")
    ap.add_argument("--led-timeout", type=float, default=2.0)
    ap.add_argument("--led-retries", type=int, default=2)

    ap.add_argument("--mode", default="TAB_AND_ANY_AV",
                    choices=["TAB_ONLY", "TAB_AND_ANY_AV", "TAB_AND_BOTH_AV"])

    ap.add_argument("--av", dest="av_enabled", action="store_true",
                    help="Enable mic/cam detection (PipeWire mic + fuser camera)")
    ap.add_argument("--no-av", dest="av_enabled", action="store_false")
    ap.set_defaults(av_enabled=False)

    ap.add_argument("--mic-app-hint", default="chromium",
                    help="Match PipeWire mic stream application.name contains this (e.g. chromium, chrome, firefox)")
    ap.add_argument("--video-dev", action="append", default=[],
                    help="Add a video device to check (repeatable), e.g. --video-dev /dev/video0")

    ap.add_argument("--poll", type=float, default=1.0)
    ap.add_argument("--debounce", type=float, default=0.5)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    httpd = HTTPServer((args.listen, args.port), Handler)
    httpd.verbose = args.verbose
    httpd.led_base = args.led_base.rstrip("/")
    httpd.led_timeout = args.led_timeout
    httpd.led_retries = args.led_retries
    httpd.mode = args.mode
    httpd.av_enabled = args.av_enabled
    httpd.mic_app_hint = args.mic_app_hint
    httpd.video_devices = tuple(args.video_dev) if args.video_dev else VIDEO_DEVICES_DEFAULT
    httpd.poll_seconds = max(0.25, args.poll)
    httpd.debounce_sec = max(0.0, args.debounce)

    print(f"Listening on http://{args.listen}:{args.port}/event  (health: /health, debug: /debug)")
    if httpd.led_base:
        print(f"Driving LED at {httpd.led_base} (endpoints: /led/on, /led/off)")
    else:
        print("LED disabled (no --led).")
    print(f"MODE={httpd.mode}  AV={'ON' if httpd.av_enabled else 'OFF'}  poll={httpd.poll_seconds}s debounce={httpd.debounce_sec}s")

    t = threading.Thread(target=loop, args=(httpd,), daemon=True)
    t.start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()

