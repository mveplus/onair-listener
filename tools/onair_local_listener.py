#!/usr/bin/env python3
"""
ON-AIR Listener (resilient)

Receives:
  GET /event?state=ON|OFF&service=meet|teams|zoom&url=...

Optionally drives LED:
  GET http://LED_HOST/led/on
  GET http://LED_HOST/led/off

Features:
- --verbose logs every request + LED action
- /health endpoint for debugging
- Debounce + state-change-only (prevents spam)
- Retry with backoff for LED calls
- Robust error responses (still returns 200 unless you want strict)
"""

import argparse
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

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
                # simple backoff: 0.2s, 0.5s, 1.0s...
                sleep_s = [0.2, 0.5, 1.0, 2.0][min(attempt, 3)]
                if verbose:
                    print(f"[{time.ctime()}] LED retry {attempt+1}/{retries} after error: {e} (sleep {sleep_s}s)")
                time.sleep(sleep_s)

    return False, f"LED failed: {last_err}"

class State:
    last_state = None
    last_change_ts = 0.0

class Handler(BaseHTTPRequestHandler):
    server_version = "onair-listener/1.2"

    def _send(self, code: int, body: str):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write((body + "\n").encode("utf-8"))

    def log_message(self, fmt, *args):
        # Only log default HTTP lines when verbose is enabled
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    def do_GET(self):
        u = urlparse(self.path)

        if u.path == "/health":
            self._send(200, "ok")
            return

        if u.path not in ("/event", "/"):
            self._send(404, "not found (use /event or /health)")
            return

        q = parse_qs(u.query)
        state = (q.get("state", [""])[0] or "").upper()
        service = (q.get("service", [""])[0] or "")
        page_url = (q.get("url", [""])[0] or "")

        if getattr(self.server, "verbose", False):
            print(f"[{time.ctime()}] REQ {u.path} state={state!r} service={service!r} url={page_url[:120]!r}")

        if state not in ("ON", "OFF"):
            self._send(200, "ignored (state must be ON or OFF)")
            return

        now = time.time()

        # State-change-only + debounce
        if State.last_state == state and (now - State.last_change_ts) < self.server.debounce_sec:
            if self.server.verbose:
                print(f"[{time.ctime()}] IGNORE duplicate {state} within {self.server.debounce_sec}s")
            self._send(200, f"ignored duplicate {state}")
            return

        ok, msg = led_call(
            led_base=self.server.led_base,
            state=state,
            timeout=self.server.led_timeout,
            retries=self.server.led_retries,
            verbose=self.server.verbose
        )

        State.last_state = state
        State.last_change_ts = now

        if self.server.verbose:
            print(f"[{time.ctime()}] EVENT {state} -> {msg}")

        self._send(200, msg if ok else f"warning: {msg}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", default="127.0.0.1", help="127.0.0.1 for local-only, 0.0.0.0 to accept LAN")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--led", dest="led_base", default="", help="e.g. http://192.168.1.172")
    ap.add_argument("--led-timeout", type=float, default=2.0)
    ap.add_argument("--led-retries", type=int, default=2)
    ap.add_argument("--debounce", type=float, default=0.5, help="seconds")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    httpd = HTTPServer((args.listen, args.port), Handler)
    httpd.led_base = args.led_base.rstrip("/")
    httpd.led_timeout = args.led_timeout
    httpd.led_retries = args.led_retries
    httpd.debounce_sec = args.debounce
    httpd.verbose = args.verbose

    print(f"Listening on http://{args.listen}:{args.port}/event  (health: /health)")
    if httpd.led_base:
        print(f"Driving LED at {httpd.led_base} (endpoints: /led/on, /led/off)")
    else:
        print("LED disabled (no --led).")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()

