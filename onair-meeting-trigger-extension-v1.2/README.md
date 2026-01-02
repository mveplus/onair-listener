# ON-AIR Meeting Trigger (Chromium Extension) — Simplified

## What this version does
- Detect Meet / Teams / Zoom tabs
- Trigger mode:
  - Any matching tab exists (pre-join)
  - Active tab only (focused)
- Optional: notify a local HTTP listener
- Optional: control your LED sign directly:
  - GET /led/on
  - GET /led/off
- Toolbar icon:
  - **Grayscale when OFF**
  - **Color when ON**

## Install
1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select the unzipped folder

## Listener event format
If Listener URL is set, the extension calls:
`/event?state=ON|OFF&service=meet|teams|zoom&url=...&ts=...`

