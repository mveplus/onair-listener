# ON-AIR Meeting Trigger (Chromium Extension)

This extension detects when **Google Meet**, **Microsoft Teams**, or **Zoom** tabs are open (or active — depending on mode) and then triggers **one or more local/LAN outputs**.

It’s designed for “ON AIR” lights, LED signs, Tasmota/Shelly relays, or any IoT device that can be controlled via **HTTP hooks**.

---

## What it does

- Detects meeting tabs for:
  - Google Meet (`meet.google.com`)
  - Microsoft Teams (`teams.microsoft.com`)
  - Zoom (`zoom.us`, `app.zoom.us`)
- Supports two detection modes:
  - **Any matching tab exists** (works even pre-join)
  - **Only when matching tab is active**
- When state changes, fires **Targets** (multiple outputs supported)

State is either:
- `ON` (a matching meeting tab exists / is active)
- `OFF` (no matching meeting tab)

---

## Targets (outputs)

You can add **multiple targets** and enable/disable them independently:

### 1) Listener target (original local listener support)
Calls your local service (for example a Python listener on your machine) using a URL.

Example (recommended with tokens):
```
http://127.0.0.1:8765/event?state={state}&service={service}&url={url}&ts={ts}
```

Backward compatibility:
- If your listener URL **does not** include tokens, the extension will append:
  `?state=...&service=...&url=...&ts=...`

### 2) Simple LED target (original direct LED support)
For the original LED device API:
- `GET /led/on`
- `GET /led/off`
- Optional `GET /led/status` (if “Verify” is enabled)

Base URL example:
```
http://192.168.1.17
```

### 3) HTTP Hook target (universal IoT control)
This is the **generic** target that can drive almost any IoT device that exposes HTTP endpoints.

Config includes:
- ON URL / OFF URL
- Method: `GET`, `POST`, `PUT`
- Optional headers (one per line: `Key: Value`)
- Optional body (tokens supported)
- Optional Basic Auth (`user:pass`)

#### Tasmota example
Turn a Tasmota relay on/off via HTTP:

ON URL:
```
http://192.168.1.17/cm?cmnd=Power%20On
```

OFF URL:
```
http://192.168.1.17/cm?cmnd=Power%20Off
```

Method:
- `GET`

No headers/body needed for typical Tasmota setups.

---

## Tokens (templating)

In Listener and HTTP Hook targets, you can use:

- `{state}` → `ON` or `OFF`
- `{service}` → `meet`, `teams`, `zoom` (or `test` during Test buttons)
- `{url}` → the meeting tab URL (when available)
- `{ts}` → timestamp (unix ms)

---

## Installation (Chrome / Chromium / Edge)

1. Open: `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select the extension folder

---

## Permissions

The extension requests host permissions **only for the targets you configure**, for example:
- `http://127.0.0.1/*`
- `http://192.168.1.17/*`

You’ll be prompted to allow these when you save settings.

---

## Testing

Open the extension **Settings** page and use:

- **Test ALL ON**
- **Test ALL OFF**

These will send requests to every enabled target.

---

## Notes / troubleshooting

- If a target is not reachable, it won’t block other targets.
- If your IoT device requires authentication, use the HTTP Hook target’s Basic Auth or headers.
- For HTTPS devices with self-signed certs, your browser may block requests unless the cert is trusted.

---

## Changelog (local)

### Universal Targets update
- Added multi-target outputs (Listener / Simple LED / HTTP Hook)
- Kept backward compatibility with previous `listenerUrl` and `direct` settings
- Added token-based templating for easy integration with IoT endpoints
