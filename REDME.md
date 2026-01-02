# ON‑AIR Indicator (Chromium + Linux)

A clean, local‑only **ON‑AIR light controller** for Google Meet, Microsoft Teams and Zoom.

It answers one question only:

> **Should my ON‑AIR light be ON right now?**

Based on:
- Am I in a meeting?
- Am I actually live (mic and/or camera)?
- Where should the LED be controlled?

No cloud. No telemetry. No guessing.

---

## Two ways to run it

### Option A — **Browser Extension + Listener** (recommended)
- Chromium extension detects meeting tabs
- Sends simple ON / OFF events to the listener
- Listener optionally gates by mic/camera
- Listener controls the LED

**Best UX. Most reliable.**

### Option B — **Listener only (no extension)**
- Listener polls Chrome DevTools:
  `http://127.0.0.1:9222/json`
- Detects meeting tabs directly
- Optional mic/camera gating
- Controls the LED

**Good for minimal setups or headless automation.**

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

## Installation prerequisites (Linux)

### Microphone detection (PipeWire)
```bash
sudo dnf install -y pipewire-utils        # Fedora
sudo apt install -y pipewire-utils        # Debian/Ubuntu
```

### Camera detection
```bash
sudo dnf install -y psmisc                # Fedora
sudo apt install -y psmisc                # Debian/Ubuntu
sudo usermod -aG video $USER
# log out and back in
```

---

## Option A — Extension + Listener

### 1) Install the extension
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
python3 onair_listener_v4.py \
  --meeting-source extension \
  --onair-mode meeting-and-mic-or-camera \
  --enable-av-detection \
  --mic-app-match chromium,chrome \
  --led http://192.168.1.172 \
  --verbose
```

#### Simple meeting indicator
```bash
python3 onair_listener_v4.py \
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
python3 onair_listener_v4.py \
  --meeting-source devtools \
  --onair-mode meeting-and-mic-or-camera \
  --enable-av-detection \
  --debug-json http://127.0.0.1:9222/json \
  --led http://192.168.1.172 \
  --verbose
```

---

## ON‑AIR modes (plain English)

| Mode | Meaning |
|----|----|
| `meeting-only` | LED ON while in a meeting |
| `meeting-and-mic-or-camera` | LED ON only if mic **or** camera active |
| `meeting-and-mic-and-camera` | LED ON only if mic **and** camera active |

---

## Run as a systemd user service

```ini
[Unit]
Description=ON‑AIR Listener
After=network-online.target

[Service]
ExecStart=%h/bin/onair_listener_v4.py --meeting-source extension --onair-mode meeting-and-mic-or-camera --enable-av-detection --led http://192.168.1.172
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
