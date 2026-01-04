# ON‑AIR Indicator (Chromium listener)

A clean, local‑only **ON‑AIR light controller** for Google Meet, Microsoft Teams and Zoom.
Linux-focused listener with local AV detection and LED control.

This listener is decoupled from
`https://github.com/mveplus/onair-meeting-trigger/tree/main` for simplicity.
The browser extension still lives in that repo.

It answers one question only:

> **Should my ON‑AIR light be ON right now?**

Based on:
- Am I in a meeting?
- Am I actually live (mic and/or camera)?
- Where should the LED be controlled?

No cloud. No telemetry. No guessing.

---

## Three ways to run it

### Option A — **Browser Extension + Listener** (recommended)
- Chromium extension detects meeting tabs
- Sends simple ON / OFF events to the listener
- Listener optionally gates by mic/camera (Linux only)
- Listener controls the LED

**Best UX. Most reliable.**

### Option B — **Listener only (no extension)**
- Listener polls Chrome DevTools:
  `http://127.0.0.1:9222/json`
- Detects meeting tabs directly
- Optional mic/camera gating
- Controls the LED

**Good for minimal setups or headless automation.**

### Option C — **AV‑only (no browser integration, Linux)**
- Listener uses mic/camera activity as the meeting signal
- Useful for other browsers or non‑browser calls
- Requires PipeWire + `fuser` (Linux only)

---

## LED requirements

Your LED device must support:
```
GET /led/on
GET /led/off
```

Example base URL:
```
http://192.168.1.172
```

---

## Installation

### All platforms
- Python 3.8+ (no pip dependencies)

### Linux (AV detection when needed)

#### Microphone + camera detection (PipeWire)
```bash
sudo dnf install -y pipewire-utils        # Fedora
sudo apt install -y pipewire-utils        # Debian/Ubuntu
```

#### Camera detection fallback
```bash
sudo dnf install -y psmisc                # Fedora
sudo apt install -y psmisc                # Debian/Ubuntu
sudo usermod -aG video $USER
# log out and back in
```

## Option A — Extension + Listener

### 1) Install the extension
- Extension source: `https://github.com/mveplus/onair-meeting-trigger/tree/main`
- Open `chrome://extensions`
- Enable **Developer mode**
- **Load unpacked**
- Select the extension folder

Set listener URL:
```
http://127.0.0.1:8765/event
```

---

### 2) Run the listener

#### Recommended ON‑AIR logic
> LED ON when **in meeting AND mic OR camera active**

```bash
python3 onair_listener.py \
  --meeting-source extension \
  --onair-mode meeting-and-mic-or-camera \
  --app-match chromium,chrome \
  --led http://192.168.1.172 \
  --verbose
```

#### Simple meeting indicator
```bash
python3 onair_listener.py \
  --meeting-source extension \
  --onair-mode meeting-only \
  --led http://192.168.1.172
```

Debug:
```bash
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/debug
```

---

## Option B — Listener only (no extension)

### Launch Chromium with DevTools enabled

#### Native / RPM / DEB
```bash
chromium \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222
```

#### Snap
```bash
mkdir -p ~/snap/chromium/common/onair-profile
snap run chromium \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 \
  --user-data-dir=$HOME/snap/chromium/common/onair-profile
```

#### Flatpak (Ungoogled Chromium)
```bash
flatpak run io.github.ungoogled_software.ungoogled_chromium \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 \
  --user-data-dir=$HOME/.config/chromium-meet-monitor
```

Verify:
```bash
curl http://127.0.0.1:9222/json | head
```

---

### Run listener (DevTools mode)

```bash
python3 onair_listener.py \
  --meeting-source devtools \
  --onair-mode meeting-and-mic-or-camera \
  --debug-json http://127.0.0.1:9222/json \
  --led http://192.168.1.172 \
  --verbose
```

---

## Option C — AV‑only (Linux)

```bash
python3 onair_listener.py \
  --meeting-source av \
  --onair-mode meeting-only \
  --app-match chromium,chrome \
  --led http://192.168.1.172 \
  --verbose
```

Note: `meeting-only` here means “mic or camera active.”

---

## ON‑AIR modes (plain English)

| Mode | Meaning |
|----|----|
| `meeting-only` | LED ON while in a meeting |
| `meeting-and-mic-or-camera` | LED ON only if mic **or** camera active |
| `meeting-and-mic-and-camera` | LED ON only if mic **and** camera active |

### App match policy (Linux only)
AV detection runs automatically when `--meeting-source av` is used or when the ON‑AIR mode requires mic/camera.
- Use `--app-match` to bias detection toward specific apps (comma‑separated).
- Use `--disable-av-detection` to force AV off (not allowed with `--meeting-source av`).
- Camera detection defaults to PipeWire and falls back to `fuser` if no video streams are present.
  Override with `--camera-detect pipewire` or `--camera-detect fuser`.
- `--mic-detect any` (default): if no hint matches, fall back to any active capture stream.
- `--mic-detect match`: only turns on if the hint matches a PipeWire capture stream.
PipeWire is used for mic and camera detection; `fuser` is only used for camera if PipeWire is unavailable.

### Mic limitation (Linux)
PipeWire (and pactl) do not always expose app mute state. In many setups, the mic stream
continues to report as active even when the app is muted, so the listener cannot reliably
turn OFF on mute without a browser signal or audio‑level monitoring.

---

## Extension event timeout (optional)

To prevent a stuck ON state if the extension stops sending events, the listener expires
extension ON state after 15 seconds by default (extension mode only).
Set `--event-timeout 0` to disable.

---

## Safety switch (optional)

If you want a physical/automated kill‑switch, require a confirm file before any LED change:

```bash
python3 onair_listener.py \
  --confirm-file /tmp/onair-ok \
  --meeting-source extension \
  --onair-mode meeting-only \
  --led http://192.168.1.172
```

When the file is missing, LED updates are skipped.

---

## Run as a systemd user service

```ini
[Unit]
Description=ON‑AIR Listener
After=network-online.target

[Service]
ExecStart=/usr/bin/python3 /path/to/onair_listener.py --meeting-source extension --onair-mode meeting-and-mic-or-camera --led http://192.168.1.172
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
```

Enable:
```bash
systemctl --user daemon-reload
systemctl --user enable --now onair-listener
journalctl --user -u onair-listener -f
```

---

## Security notes

- Listener binds to `127.0.0.1` by default
- DevTools must **never** bind to `0.0.0.0`
- No cloud calls
- No browser data leaves your machine

---

## Mental model

> **Meeting detection** decides *if a meeting exists*  
> **AV detection** decides *if you’re live*  
> **LED control** reflects the truth, debounced and safe
