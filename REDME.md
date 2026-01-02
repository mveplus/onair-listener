The correct way to launch Snap Chromium with DevTools
1️⃣ Pick a Snap-writable profile dir

This must live inside Snap’s home:

$HOME/snap/chromium/common/onair-profile


Create it:

mkdir -p ~/snap/chromium/common/onair-profile

2️⃣ Launch Chromium snap with debugging enabled

⚠️ You must fully exit Chromium first (no background processes).

snap run chromium \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 \
  --user-data-dir=$HOME/snap/chromium/common/onair-profile


Now test:

curl http://127.0.0.1:9222/json


If you see JSON → it works.

Important Snap-specific rules (don’t skip)
❌ This will NOT work

Launching Chromium normally, then trying to attach

Using /tmp, /var, /home/mtl/.config

Running DevTools against an existing session

✅ This DOES work

Launching Chromium explicitly via snap run chromium

Using ~/snap/chromium/common/*

Running your Python monitor outside the snap

Your existing script still works unchanged

Your DevTools-based detection:

http://127.0.0.1:9222/json


✅ Works exactly the same
✅ No Snap permissions needed
✅ No portals / DBus nonsense
✅ No extensions required

Your mic/cam detection (PipeWire + /dev/video*) is completely unaffected by Snap.

Recommended quality-of-life improvement (strongly suggested)

Create a launcher script so you don’t forget the flags:

cat > ~/bin/chromium-onair <<'EOF'
#!/usr/bin/env bash
exec snap run chromium \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 \
  --user-data-dir=$HOME/snap/chromium/common/onair-profile
EOF

chmod +x ~/bin/chromium-onair


Now just run:

chromium-onair

Security note (you’re doing this right)

DevTools is bound to 127.0.0.1 only

No LAN exposure

No Snap interface loosening required

This is safer than a browser extension

When Snap is not worth fighting

If you ever get tired of this:

Flatpak Chromium: ❌ worse for DevTools

Native .rpm Chromium: ✅ easiest

Ungoogled Chromium (rpmfusion): ✅ best for automation

But your current setup is 100% viable.

Bottom line

✔ Yes — Snap Chromium can use local DevTools
✔ Your on-air detection architecture remains valid
✔ Only requirement: launch Chromium with flags every time

If you want, next I can:

Turn this into a systemd user service

Add auto-launch Chromium when your monitor starts

Add Zoom/Teams “joined” heuristics without DOM scraping
