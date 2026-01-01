#!/usr/bin/env python3
import json, time, subprocess, urllib.request, urllib.error

# Install fuser (Fedora) if needed
# sudo dnf install -y psmisc

# Pipewire cli commanad: "pw-dump", install if not avalable out of the box:
# sudo apt-get install -y pipewire-utils
# Fedora/RHEL: sudo dnf install -y pipewire-utils

# Fix camera perms (so no sudo) only as fail-back if 
# PipeWire/Pulse on PipeWire not in use
# sudo usermod -aG video $USER
# log out + in. Then test:
# fuser -v /dev/video0

# Example of running "Ungoogled Chromium" from flatpack:
# flatpak run io.github.ungoogled_software.ungoogled_chromium --remote-debugging-address=127.0.0.1   --remote-debugging-port=9222   --user-data-dir=$HOME/.config/chromium-meet-monitor
DEBUG_JSON = "http://127.0.0.1:9222/json"

#IOT_BASE = "http://LOCAL_IP"  # e.g. http://192.168.1.50
IOT_BASE = "http://192.168.1.172"  # e.g. http://192.168.1.50
IOT_ON  = f"{IOT_BASE}/led/on"
IOT_OFF = f"{IOT_BASE}/led/off"

POLL_SECONDS = 1.0
DEBOUNCE_SECONDS = 2.0

MEETING_URL_PREFIXES = (
    "https://meet.google.com/",
    "https://teams.microsoft.com/",
    "https://zoom.us/",
    "https://app.zoom.us/",
)

VIDEO_DEVICES = ("/dev/video0", "/dev/video1")  # extend if you have more

def http_get(url: str, timeout: float = 2.0) -> int:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.getcode()

def meeting_tab_open() -> bool:
    try:
        with urllib.request.urlopen(DEBUG_JSON, timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, json.JSONDecodeError):
        return False

    for t in data:
        url = (t.get("url") or "").strip()
        if url.startswith(MEETING_URL_PREFIXES):
            return True
    return False

def _pw_dump():
    out = subprocess.check_output(["pw-dump"], text=True)
    return json.loads(out)

def _props(obj):
    return (obj.get("info") or {}).get("props") or obj.get("props") or {}

def mic_in_use() -> bool:
    # Confirmed on your system: Stream/Input/Audio + "Chromium input"
    for o in _pw_dump():
        p = _props(o)
        mc = (p.get("media.class") or "")
        app = (p.get("application.name") or "").lower()
        if mc == "Stream/Input/Audio" and "chromium" in app:
            return True
    return False

def camera_in_use() -> bool:
    # Kernel-truth: is /dev/video* busy?
    # Uses fuser; requires user in 'video' group or sudo.
    for dev in VIDEO_DEVICES:
        try:
            # fuser exits 0 if any process is using the file, else non-zero
            subprocess.check_output(["fuser", dev], stderr=subprocess.DEVNULL)
            return True
        except subprocess.CalledProcessError:
            continue
        except FileNotFoundError:
            # fuser not installed (psmisc package)
            return False
    return False

def desired_led_state() -> bool:
    if not meeting_tab_open():
        return False
    return mic_in_use() and camera_in_use()

def main():
    last_raw = None
    stable_since = None
    stable_state = None
    last_sent = None

    while True:
        raw = desired_led_state()

        if raw != last_raw:
            last_raw = raw
            stable_since = time.time()

        if stable_since is not None and (time.time() - stable_since) >= DEBOUNCE_SECONDS:
            stable_state = raw

        if stable_state is not None and stable_state != last_sent:
            try:
                code = http_get(IOT_ON if stable_state else IOT_OFF)
                print(f"[{time.ctime()}] LED {'ON' if stable_state else 'OFF'} (HTTP {code})")
                last_sent = stable_state
            except Exception as e:
                print(f"[{time.ctime()}] IoT call failed: {e}")

        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()

