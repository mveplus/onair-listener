#!/usr/bin/env python3
"""
ON-AIR Listener (extension + DevTools, optional mic/cam)

Two input sources (choose one):
  1) Extension events (recommended UX)
     - Extension sends: GET /event?state=ON|OFF&service=...&url=...
     - Listener decides final ON-AIR using MODE (+ optional mic/cam)
  2) Chrome DevTools polling (no extension)
     - Listener polls: http://127.0.0.1:9222/json
     - Detects meeting tabs by URL prefixes

Optional truth signals:
  - Mic in use: PipeWire (pw-dump)
  - Camera in use: /dev/video* busy check (fuser)

Outputs:
  - Drive LED sign on LAN: GET /led/on and /led/off
  - Write state JSON to a file (for debugging/automation)

Security defaults:
  - HTTP listener binds to 127.0.0.1 (local-only) unless you override.
  - DevTools must bind to 127.0.0.1 (local-only).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import threading
import time
import subprocess
import urllib.request
import urllib.error
from dataclasses import dataclass, asdict, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional, Tuple
from urllib.parse import urlparse, parse_qs

# -------------------------
# Defaults / constants
# -------------------------

MEETING_URL_PREFIXES_DEFAULT = (
    "https://meet.google.com/",
    "https://teams.microsoft.com/",
    "https://zoom.us/",
    "https://app.zoom.us/",
)

VIDEO_DEVICES_DEFAULT = ("/dev/video0", "/dev/video1")


# -------------------------
# Data models
# -------------------------

@dataclass
class MeetingSignal:
    meeting_open: bool = False
    service: str = ""
    url: str = ""
    ts: float = 0.0


@dataclass
class AvSignal:
    mic: Optional[bool] = None
    cam: Optional[bool] = None
    ts: float = 0.0


@dataclass
class OutputState:
    desired: str = "OFF"  # ON or OFF
    last_sent: Optional[str] = None
    last_sent_ts: float = 0.0


@dataclass
class RuntimeState:
    meeting: MeetingSignal = field(default_factory=MeetingSignal)
    av: AvSignal = field(default_factory=AvSignal)
    out: OutputState = field(default_factory=OutputState)

    def to_json(self) -> str:
        # Flatten for readability
        payload = {
            "meeting": asdict(self.meeting),
            "av": asdict(self.av),
            "output": asdict(self.out),
        }
        return json.dumps(payload, indent=2, sort_keys=True)


# -------------------------
# Helpers
# -------------------------

def http_get(url: str, timeout: float) -> int:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.getcode()


def retry_get(url: str, timeout: float, retries: int, log: logging.Logger) -> Tuple[bool, str]:
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            code = http_get(url, timeout=timeout)
            return True, f"HTTP {code}"
        except Exception as e:
            last_err = e
            if attempt < retries:
                backoff = [0.2, 0.5, 1.0, 2.0][min(attempt, 3)]
                log.warning("GET failed (%s). Retrying in %.1fs (%d/%d): %s", url, backoff, attempt+1, retries, e)
                time.sleep(backoff)
    return False, f"failed: {last_err}"


def safe_write(path: str, content: str, log: logging.Logger) -> None:
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception as e:
        log.warning("Failed to write state file %s: %s", path, e)


# -------------------------
# Mic/cam detection
# -------------------------

def av_in_use_pipewire(
    app_hints: str,
    log: logging.Logger,
    verbose_dump: bool = False,
    allow_fallback: bool = True,
) -> Tuple[bool, bool, bool, bool]:
    """
    PipeWire mic/camera capture detection using pw-dump JSON.

    What can go wrong in practice:
      - application.name varies ("Chromium input", "Google Chrome input", etc.)
      - some sessions omit application.process.binary
      - node state fields differ across PipeWire versions

    Strategy (robust):
      1) Prefer a match against (application.name + application.process.binary + node.description + node.name)
         using a comma-separated hint list (e.g. "chromium,chrome,brave").
      2) If no match hits and allow_fallback=True, fall back to any capture stream exists
         (Stream/Input/Audio or Stream/Input/Video).

    If verbose_dump=True, we log the candidate capture streams to help tune hints.
    """
    hints = [h.strip().lower() for h in (app_hints or "").split(",") if h.strip()]
    if not hints:
        hints = ["chromium"]

    try:
        out = subprocess.check_output(["pw-dump"], text=True)
        data = json.loads(out)

        def props(o):
            return (o.get("info") or {}).get("props") or o.get("props") or {}

        audio_streams = []
        video_streams = []
        for o in data:
            p = props(o)
            media_class = (p.get("media.class") or "").strip()
            if media_class not in ("Stream/Input/Audio", "Stream/Input/Video"):
                continue

            app_name = (p.get("application.name") or "").strip()
            app_bin  = (p.get("application.process.binary") or "").strip()
            node_desc = (p.get("node.description") or "").strip()
            node_name = (p.get("node.name") or "").strip()

            # Some PipeWire versions expose state at info.state, others not.
            info = o.get("info") or {}
            node_state = (info.get("state") or "").strip()

            hay = f"{app_name} {app_bin} {node_desc} {node_name}".lower().strip()
            item = (hay, app_name, app_bin, node_desc, node_name, node_state)
            if media_class == "Stream/Input/Audio":
                audio_streams.append(item)
            else:
                video_streams.append(item)

        if verbose_dump and (audio_streams or video_streams):
            if audio_streams:
                log.info("PipeWire capture streams (Stream/Input/Audio):")
                for (_hay, app_name, app_bin, node_desc, node_name, node_state) in audio_streams[:30]:
                    log.info("  app=%r bin=%r desc=%r name=%r state=%r", app_name, app_bin, node_desc, node_name, node_state)
            if video_streams:
                log.info("PipeWire capture streams (Stream/Input/Video):")
                for (_hay, app_name, app_bin, node_desc, node_name, node_state) in video_streams[:30]:
                    log.info("  app=%r bin=%r desc=%r name=%r state=%r", app_name, app_bin, node_desc, node_name, node_state)

        def any_match(streams):
            return any(any(h in hay for h in hints) for (hay, *_rest) in streams)

        mic_match = any_match(audio_streams)
        cam_match = any_match(video_streams)

        has_video = len(video_streams) > 0
        if allow_fallback:
            mic = mic_match or len(audio_streams) > 0
            cam = cam_match or has_video
        else:
            mic = mic_match
            cam = cam_match

        return mic, cam, True, has_video

    except FileNotFoundError:
        log.debug("pw-dump not found; install pipewire-utils to enable mic/camera detection")
        return False, False, False, False
    except Exception as e:
        log.debug("pw-dump AV detection failed: %s", e)
        return False, False, False, False


def camera_in_use_fuser(video_devices: Tuple[str, ...], log: logging.Logger) -> bool:
    """
    Camera detection via /dev/video* busy check (fuser).
    """
    try:
        for dev in video_devices:
            try:
                subprocess.check_output(["fuser", dev], stderr=subprocess.DEVNULL)
                return True
            except subprocess.CalledProcessError:
                continue
        return False
    except FileNotFoundError:
        log.debug("fuser not found; install psmisc to enable camera detection")
        return False
    except Exception as e:
        log.debug("fuser camera detection failed: %s", e)
        return False


# -------------------------
# Meeting detection sources
# -------------------------

def meeting_from_devtools(debug_json: str, prefixes: Tuple[str, ...], timeout: float, log: logging.Logger) -> MeetingSignal:
    """
    Poll Chrome DevTools /json endpoint and look for matching URLs.
    """
    sig = MeetingSignal(meeting_open=False, service="", url="", ts=time.time())
    try:
        with urllib.request.urlopen(debug_json, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:
        log.debug("DevTools poll failed (%s): %s", debug_json, e)
        return sig

    for t in data:
        url = (t.get("url") or "").strip()
        for p in prefixes:
            if url.startswith(p):
                # service is the hostname-ish label
                if "meet.google.com" in url:
                    svc = "meet"
                elif "teams.microsoft.com" in url:
                    svc = "teams"
                elif "zoom.us" in url:
                    svc = "zoom"
                else:
                    svc = "meeting"
                return MeetingSignal(meeting_open=True, service=svc, url=url, ts=time.time())
    return sig


# -------------------------
# Policy (MODE)
# -------------------------

def compute_desired(mode: str, meeting_open: bool, mic: bool, cam: bool) -> str:
    if not meeting_open:
        return "OFF"
    if mode == "meeting-only":
        return "ON"
    if mode == "meeting-and-mic-or-camera":
        return "ON" if (mic or cam) else "OFF"
    if mode == "meeting-and-mic-and-camera":
        return "ON" if (mic and cam) else "OFF"
    return "OFF"


# -------------------------
# HTTP server for extension events
# -------------------------

class EventHandler(BaseHTTPRequestHandler):
    server_version = "onair-listener/3.0"

    def log_message(self, fmt, *args):
        # We use logging module instead.
        return

    def _send(self, code: int, body: str, content_type: str = "text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write((body + "\n").encode("utf-8"))

    def do_GET(self):
        u = urlparse(self.path)
        srv: "OnairServer" = self.server  # type: ignore

        if u.path == "/health":
            self._send(200, "ok")
            return

        if u.path == "/debug":
            with srv.lock:
                self._send(200, srv.state.to_json(), "application/json; charset=utf-8")
            return

        if u.path not in ("/event", "/"):
            self._send(404, "not found (use /event, /health, /debug)")
            return

        q = parse_qs(u.query)
        ev_state = (q.get("state", [""])[0] or "").upper()
        service = (q.get("service", [""])[0] or "")
        page_url = (q.get("url", [""])[0] or "")

        if ev_state not in ("ON", "OFF"):
            self._send(200, "ignored (state must be ON or OFF)")
            return

        with srv.lock:
            srv.state.meeting = MeetingSignal(
                meeting_open=(ev_state == "ON"),
                service=service,
                url=page_url,
                ts=time.time()
            )

        srv.log.info("EXT event: %s service=%s url=%s", ev_state, service, page_url[:120])
        self._send(200, "ok")


class OnairServer(HTTPServer):
    def __init__(self, addr, handler, state: RuntimeState, lock: threading.Lock, log: logging.Logger):
        super().__init__(addr, handler)
        self.state = state
        self.lock = lock
        self.log = log


# -------------------------
# Main loop
# -------------------------

def run_loop(args, state: RuntimeState, lock: threading.Lock, log: logging.Logger):
    """
    Poll source signals + optional AV signals and drive output.
    """
    prefixes = tuple(args.meeting_prefix)
    video_devices = tuple(args.video_dev)

    while True:
        time.sleep(args.poll)

        # 1) Update meeting state from chosen source
        if args.source == "devtools":
            sig = meeting_from_devtools(args.debug_json, prefixes, args.devtools_timeout, log)
            with lock:
                state.meeting = sig
        elif args.source == "extension":
            # Extension events can go stale if the browser/extension dies mid-meeting.
            if args.event_timeout > 0:
                now = time.time()
                with lock:
                    if state.meeting.meeting_open and (now - state.meeting.ts) > args.event_timeout:
                        state.meeting = MeetingSignal(meeting_open=False, service="", url="", ts=now)
                        log.info("Extension meeting state expired after %.1fs", args.event_timeout)

        # 2) AV detection (only when needed)
        with lock:
            meeting_open = state.meeting.meeting_open

        mic = False
        cam = False
        av_needed = ((args.source == "av") or (args.mode != "meeting-only")) and not args.disable_av_detection
        if av_needed and (meeting_open or args.source == "av"):
            mic, cam, pw_ok, pw_has_video = av_in_use_pipewire(
                args.app_hint,
                log,
                verbose_dump=args.verbose,
                allow_fallback=(args.mic_detect == "any"),
            )
            if args.camera_detect == "fuser":
                cam = camera_in_use_fuser(video_devices, log)
            elif args.camera_detect == "auto" and (not pw_ok or not pw_has_video):
                if not pw_ok:
                    log.info("Camera detect auto: PipeWire unavailable; falling back to fuser")
                elif not pw_has_video:
                    log.info("Camera detect auto: no PipeWire video streams; falling back to fuser")
                cam = camera_in_use_fuser(video_devices, log)
            with lock:
                state.av = AvSignal(mic=mic, cam=cam, ts=time.time())
            log.info("AV: mic=%s cam=%s (hint=%s)", mic, cam, args.app_hint)
        else:
            with lock:
                state.av = AvSignal(mic=None, cam=None, ts=time.time())

        # 2b) If AV is the meeting source, derive meeting state from AV activity.
        if args.source == "av":
            now = time.time()
            with lock:
                state.meeting = MeetingSignal(
                    meeting_open=bool(mic or cam),
                    service="av",
                    url="",
                    ts=now,
                )
            meeting_open = bool(mic or cam)

        # 3) Decide desired state
        desired = compute_desired(args.mode, meeting_open, mic, cam)

        # 4) Write state file (debug/automation)
        with lock:
            state.out.desired = desired
            if args.state_file:
                safe_write(args.state_file, state.to_json(), log)

        # 5) Output: LED (debounced + state-change-only)
        with lock:
            last = state.out.last_sent
            last_ts = state.out.last_sent_ts

        now = time.time()
        if desired == last:
            continue
        if (now - last_ts) < args.debounce:
            continue

        if args.led and args.confirm_file and not os.path.exists(args.confirm_file):
            log.info("LED update skipped; confirm file missing: %s", args.confirm_file)
            continue

        if args.led:
            led_url = args.led.rstrip("/") + ("/led/on" if desired == "ON" else "/led/off")
            ok, msg = retry_get(led_url, timeout=args.led_timeout, retries=args.led_retries, log=log)
            log.info("LED %s -> %s (%s)", desired, led_url, msg)
        else:
            log.info("Desired=%s (LED disabled; no --led)", desired)

        with lock:
            state.out.last_sent = desired
            state.out.last_sent_ts = now


def build_argparser():
    ap = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="ON-AIR Listener (Extension events OR DevTools polling) with optional mic/cam detection."
    )

    ap.add_argument("--meeting-source", "--source", dest="source", choices=["extension", "devtools", "av"], default="extension",
                    help="Where meeting state comes from: extension HTTP events, DevTools polling, or local AV activity")
    ap.add_argument("--onair-mode", "--mode", dest="mode", choices=["meeting-only","meeting-and-mic-or-camera","meeting-and-mic-and-camera"], default="meeting-only",
                    help="Policy for ON-AIR based on meeting + optional AV signals")

    # Extension HTTP server
    ap.add_argument("--listen", default="127.0.0.1", help="Bind address for HTTP listener (extension mode)")
    ap.add_argument("--port", type=int, default=8765, help="Port for HTTP listener (extension mode)")
    ap.add_argument("--event-timeout", type=float, default=15.0,
                    help="Seconds before extension ON state expires (0 disables)")

    # DevTools polling
    ap.add_argument("--debug-json", default="http://127.0.0.1:9222/json", help="Chrome DevTools /json endpoint")
    ap.add_argument("--devtools-timeout", type=float, default=1.5, help="Timeout for DevTools polling (seconds)")

    # Meeting URL prefixes
    ap.add_argument("--meeting-prefix", action="append", default=list(MEETING_URL_PREFIXES_DEFAULT),
                    help="Meeting URL prefixes to match (repeatable)")

    # Optional AV
    ap.add_argument("--app-match", "--app-hint", dest="app_hint", default="chromium", help="Comma-separated hints to match PipeWire application.name / application.process.binary (e.g. chromium,chrome)")
    ap.add_argument("--disable-av-detection", action="store_true",
                    help="Disable mic/camera detection (not allowed with --meeting-source av)")
    ap.add_argument("--camera-detect", choices=["auto", "pipewire", "fuser"], default="auto",
                    help="Camera detection source: auto (PipeWire then fuser), pipewire only, or fuser only")
    ap.add_argument("--mic-detect", choices=["any", "match"], default="any",
                    help="Mic detection policy: match hint only, or allow fallback to any capture stream")
    ap.add_argument("--video-dev", action="append", default=list(VIDEO_DEVICES_DEFAULT),
                    help="Video device(s) to check with fuser (repeatable)")

    # Output: LED
    ap.add_argument("--led", default="", help="LED base URL, e.g. http://192.168.1.172")
    ap.add_argument("--led-timeout", type=float, default=2.0, help="HTTP timeout for LED calls")
    ap.add_argument("--led-retries", type=int, default=2, help="Retries for LED calls")

    # Resilience
    ap.add_argument("--poll", type=float, default=1.0, help="Polling interval (seconds)")
    ap.add_argument("--debounce", type=float, default=0.5, help="Minimum seconds between LED state changes")

    # Debug / automation
    ap.add_argument("--state-file", default="", help="Write current state JSON to this file")
    ap.add_argument("--confirm-file", default="",
                    help="If set, LED actions only happen when this file exists (safety switch)")

    # Logging
    ap.add_argument("--verbose", action="store_true", help="Verbose logging (INFO). Otherwise warnings only.")
    return ap


def main():
    ap = build_argparser()
    args = ap.parse_args()

    if args.disable_av_detection and args.source == "av":
        ap.error("--disable-av-detection cannot be used with --meeting-source av")

    log = logging.getLogger("onair")
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    state = RuntimeState()
    lock = threading.Lock()

    # Start HTTP server only if source is extension OR you want debug endpoints.
    httpd = None
    if args.source == "extension":
        httpd = OnairServer((args.listen, args.port), EventHandler, state, lock, log)
        log.info("HTTP listener on http://%s:%d (endpoints: /event, /health, /debug)", args.listen, args.port)

    # Start main loop thread
    t = threading.Thread(target=run_loop, args=(args, state, lock, log), daemon=True)
    t.start()

    # Serve forever (extension mode), or just keep process alive (devtools mode)
    try:
        if httpd:
            print(f"Listening on http://{args.listen}:{args.port}/event  (health: /health, debug: /debug)")
        else:
            print("DevTools mode: no HTTP listener. Polling:", args.debug_json)

        if args.led:
            print("Driving LED:", args.led.rstrip("/"), "(/led/on, /led/off)")
        else:
            print("LED disabled (no --led)")

        av_enabled = ((args.source == "av") or (args.mode != "meeting-only")) and not args.disable_av_detection
        print("MEETING_SOURCE=", args.source, "ONAIR_MODE=", args.mode, "AV_DETECTION=", "ON" if av_enabled else "OFF", "AV_MATCH=", args.app_hint,
              "CAMERA_DETECT=", args.camera_detect, "poll=", args.poll, "debounce=", args.debounce, "event_timeout=", args.event_timeout)

        if args.mode != "meeting-only" and not av_enabled:
            print("NOTE: You selected MODE that depends on mic/cam, but AV detection is OFF.")

        if args.confirm_file:
            print("Safety confirm file:", args.confirm_file)

        if args.state_file:
            print("State file:", args.state_file)

        if httpd:
            httpd.serve_forever()
        else:
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
