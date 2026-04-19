# OpenCode GUI, Memory, WiFi, and GitHub Report
## March 24, 2026

---

## 1. OpenCode GUI Summary

**Service Name:** opencode-gui.service  
**Status:** ✅ Active and running  
**Enabled:** Yes (starts on boot)  
**Port:** 11434  
**Version:** 1.3.2  

**Browser URLs:**
- http://localhost:11434
- http://192.168.68.51:11434
- http://opencode.local:11434 (mDNS)

**Service File:** /etc/systemd/system/opencode-gui.service

**Changes Made:**
- Added ExecStartPre to run memory bootstrap script
- Service now integrates with durable memory system

---

## 2. Durable Memory Summary

**Memory Directory:** /opt/ai/mem/

**Created Files:**
- state.md - System state snapshot
- tasks.md - Unfinished task ledger
- log.md - Append-only operational log
- episodic.jsonl - Session history
- facts.json - Fact store
- failure_memory.json - Known failures and workarounds
- workflows.json - Workflow patterns
- last_session.json - Recovery pointer
- MEMORY_SYSTEM.md - Memory system documentation

**Created Skills:**
- /home/mikoleye/.opencode/skills/opencode-memory/SKILL.md
- /home/mikoleye/.opencode/skills/opencode-resume/SKILL.md
- /home/mikoleye/.opencode/skills/opencode-ops/SKILL.md

**Helper Scripts:**
- /home/mikoleye/opencode-memory-bootstrap.sh - Runs on service startup

**Recovery:** On startup, service reads last_session.json and tasks.md to restore context.

---

## 3. WiFi Findings

**Hardware:** RTL8723BU USB WiFi (0bda:b720)  
**Interface:** wlx0013eff5566c  
**Driver:** rtl8xxxu (in-kernel)  
**Status:** ⚠️ Driver loads, association succeeds, WPA handshake times out  

**Root Cause:** rtl8xxxu driver incompatibility with ASUS RT-AC68U router

**Error Pattern:**
```
wpa_supplicant: 4WAY_HANDSHAKE_TIMEOUT
dmesg: deauthenticated from d4:5d:64:19:c9:34 (Reason: 15)
```

**Router-Side Fix Required:**
To use this adapter with the ASUS router, manually configure:

1. Go to ASUS router GUI: http://192.168.68.62
2. Login with admin credentials
3. Wireless > Professional
4. Set:
   - Band: 2.4GHz only
   - Channel Width: 20MHz
   - Security: WPA2-Personal
   - Encryption: AES/CCMP only
   - WPA3: Disabled
   - PMF: Optional or Disabled
5. Save and apply

**Current Status:** Ethernet (enp2s0) at 192.168.68.51 is working as primary. WiFi is available but not connected due to driver/AP incompatibility.

---

## 4. GitHub Findings

**Karma Repo Location:** /home/mikoleye/karma  
**Status:** ❌ Does not exist

**Investigation:**
- No git repo found at /home/mikoleye/karma
- Previous mission summary noted: "karma repo: Found empty directory, no content to recover"
- No gh CLI installed

**Action Required:** The Karma repo needs to be created or restored from a backup/source. GitHub authentication not yet configured.

---

## 5. Services/Files Changed

### Systemd Services
- /etc/systemd/system/opencode-gui.service - Updated with memory bootstrap

### Memory Files Created
- /opt/ai/mem/MEMORY_SYSTEM.md
- /opt/ai/mem/state.md
- /opt/ai/mem/tasks.md
- /opt/ai/mem/log.md
- /opt/ai/mem/episodic.jsonl
- /opt/ai/mem/facts.json
- /opt/ai/mem/failure_memory.json
- /opt/ai/mem/workflows.json
- /opt/ai/mem/last_session.json

### Skills Created
- /home/mikoleye/.opencode/skills/opencode-memory/SKILL.md
- /home/mikoleye/.opencode/skills/opencode-resume/SKILL.md
- /home/mikoleye/.opencode/skills/opencode-ops/SKILL.md

### Scripts Created
- /home/mikoleye/opencode-memory-bootstrap.sh

---

## 6. Commands Run

```bash
# Memory setup
sudo mkdir -p /opt/ai/mem
sudo chown -R mikoleye:mikoleye /home/mikoleye/.opencode/skills

# Service update
sudo cp opencode-gui-upgraded.service /etc/systemd/system/opencode-gui.service
sudo systemctl daemon-reload
sudo systemctl restart opencode-gui.service

# Verify
systemctl status opencode-gui.service
curl -s http://localhost:11434
```

---

## 7. Final URLs and Resume Commands

**OpenCode GUI:** http://192.168.68.51:11434

**Memory Checkpoint:**
```bash
cat /opt/ai/mem/last_session.json
grep -A 10 "## ACTIVE" /opt/ai/mem/tasks.md
```

**Resume After Restart:**
```bash
systemctl restart opencode-gui.service
journalctl -u opencode-gui.service -f
```

---

## 8. Final Git Status

**Karma Repo:** Not present - needs creation/restoration

**To set up GitHub (when karma repo exists):**
```bash
# Install gh if needed
sudo apt install gh

# Authenticate
gh auth login

# Set remote
git remote add origin https://github.com/username/karma.git
git fetch origin
```

---

## 9. Report Location

Full report saved to: /home/mikoleye/OPENCODE_GUI_MEMORY_WIFI_GITHUB_REPORT.md