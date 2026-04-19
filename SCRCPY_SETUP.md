# scrcpy Setup - STG keyboard/mouse → Phone in DeX

## Current Status
scrcpy is installed on STG. Need to connect phone.

## Quick Setup (do this on phone)

### Option 1: Wireless ADB (recommended)
1. **Enable Developer Options:**
   - Settings → About Phone → Tap "Build Number" 7 times

2. **Enable Wireless ADB:**
   - Settings → Developer Options → Enable "Wireless ADB debugging"

3. **Pair on phone:**
   - Settings → Developer Options → Wireless ADB → "Pair device with pairing code"
   - Note the IP and port (e.g., `192.168.68.XX:5555`) and pairing code

4. **Run on STG:**
   ```bash
   adb pair 192.168.68.XX:5555
   # Enter pairing code from phone
   adb connect 192.168.68.XX:5555
   scrcpy
   ```

### Option 2: USB
1. Connect phone via USB
2. Enable "USB Debugging" in Developer Options
3. Run: `scrcpy`

## Widget
Run from Termux widget: `scrcpy.sh`

## Troubleshooting
- If scrcpy doesn't start, check: `adb devices`
- Screen off? Use: `scrcpy --turn-screen-off --stay-awake`
- Lag? Lower bitrate: `scrcpy --bit-rate 4M --max-fps 30`
