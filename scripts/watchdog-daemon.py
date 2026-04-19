#!/usr/bin/env python3
"""
Watchdog Daemon - Monitors core services and restarts if needed
"""

import os
import sys
import time
import subprocess
import json
from datetime import datetime
from pathlib import Path

LOG_FILE = "/home/mikoleye/.local/var/watchdog.log"
STATE_FILE = "/home/mikoleye/.local/var/watchdog_state.json"
CHECK_INTERVAL = 20  # seconds
MAX_RETRIES = 3

def log(msg):
    """Write to log file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except:
        pass

def load_state():
    """Load failure state."""
    try:
        if Path(STATE_FILE).exists():
            with open(STATE_FILE) as f:
                return json.load(f)
    except:
        pass
    return {}

def save_state(state):
    """Save failure state."""
    try:
        Path(STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except:
        pass

def check_process(name, port=None, path="/api/tags"):
    """Check if process is running and optionally responding on port."""
    # Check process
    result = subprocess.run(
        ["pgrep", "-f", name],
        capture_output=True
    )
    if result.returncode != 0:
        return False, "not running"
    
    # Check port if specified
    if port:
        result = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", 
             f"http://127.0.0.1:{port}{path}"],
            capture_output=True,
            timeout=5
        )
        if result.returncode != 0 or b"200" not in result.stdout:
            return False, "not responding on port"
    
    return True, "ok"

def check_ollama():
    """Check Ollama service."""
    return check_process("ollama serve", 11434, "/api/tags")

def check_openclaw():
    """Check OpenClaw gateway process.

    The current OpenClaw CLI process names are typically `openclaw` and
    `openclaw-agent` (not `openclaw-gateway`). Also avoid strict HTTP checks
    here because gateway transport may not expose a plain 200 `/` endpoint in
    all modes.
    """
    return check_process("openclaw", None)

def check_goose():
    """Check Goose service."""
    return check_process("goose", None)

def check_bridge():
    """Check bridge directories."""
    bridge_path = Path("/home/mikoleye/karma/bridge")
    if not bridge_path.exists():
        return False, "bridge dir missing"
    
    for subdir in ["inbox", "outbox", "planner"]:
        p = bridge_path / subdir
        if not p.exists():
            return False, f"bridge/{subdir} missing"
        if not os.access(p, os.W_OK):
            return False, f"bridge/{subdir} not writable"
    
    return True, "ok"

def check_system():
    """Check system health."""
    issues = []
    
    # Memory
    result = subprocess.run(
        ["free", "-h"],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        for line in result.stdout.split("\n"):
            if "Mem:" in line:
                parts = line.split()
                available = parts[6] if len(parts) > 6 else "0"
                # Low memory check
                try:
                    if "Mi" in available:
                        val = int(available.replace("Mi", ""))
                        if val < 500:
                            issues.append(f"low memory: {available}")
                except:
                    pass
    
    # Disk
    result = subprocess.run(
        ["df", "-h", "/"],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        for line in result.stdout.split("\n"):
            if "/" in line and "%" in line:
                parts = line.split()
                if len(parts) > 4:
                    try:
                        pct = int(parts[4].replace("%", ""))
                        if pct > 90:
                            issues.append(f"disk: {pct}% full")
                    except:
                        pass
    
    if issues:
        return False, ", ".join(issues)
    return True, "ok"

def restart_service(name):
    """Restart a service via systemctl."""
    log(f"Attempting to restart {name}")
    result = subprocess.run(
        ["systemctl", "restart", name],
        capture_output=True
    )
    if result.returncode == 0:
        log(f"Restarted {name} successfully")
        return True
    else:
        log(f"Failed to restart {name}: {result.stderr.decode()}")
        return False

def main():
    log("=== Watchdog Daemon Starting ===")
    
    os.makedirs("/var/log", exist_ok=True)
    os.makedirs("/var/lib", exist_ok=True)
    
    services = {
        "ollama": check_ollama,
        "openclaw-gateway": check_openclaw,
        "goose": check_goose,
        "bridge": check_bridge,
    }
    
    while True:
        state = load_state()
        
        for name, check_func in services.items():
            try:
                ok, status = check_func()
                
                if not ok:
                    log(f"CHECK FAILED: {name} - {status}")

                    # If retries were paused, keep paused until we see a healthy check.
                    if state.get(name) == -1:
                        log(f"  Retries paused for {name}; skipping restart")
                        continue

                    # Increment failure count
                    state[name] = state.get(name, 0) + 1
                    log(f"  Failure count: {state[name]}/{MAX_RETRIES}")

                    if state[name] >= MAX_RETRIES:
                        log(f"  MAX RETRIES reached for {name}, pausing")
                        state[name] = -1  # Pause retries until a successful check resets to 0
                    elif state[name] > 0:
                        # Try restart
                        restart_service(name)
                else:
                    log(f"CHECK OK: {name}")
                    state[name] = 0  # Reset on success
            except Exception as e:
                log(f"ERROR checking {name}: {e}")
        
        # System check
        try:
            ok, status = check_system()
            if not ok:
                log(f"SYSTEM WARNING: {status}")
        except Exception as e:
            log(f"ERROR checking system: {e}")
        
        save_state(state)
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("=== Watchdog Daemon Stopped ===")
        sys.exit(0)