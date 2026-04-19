# Memory Backup Lifecycle - Quick Reference

## Overview
30-day on-phone retention with USB archive for karma memory/logs.

## Files
- `/home/mikoleye/memory_backup.py` - Main script
- `/home/mikoleye/memory_backup.config` - Configuration

## Commands

```bash
# Check backup status
python3 ~/memory_backup.py status

# Run backup to USB
python3 ~/memory_backup.py backup

# Search archived memory
python3 ~/memory_backup.py search "keyword"

# Retrieve memory from specific days ago
python3 ~/memory_backup.py retrieve 30
```

## Configuration
Edit `memory_backup.config`:
- `RETENTION_DAYS=30` - Days to keep on phone
- `USB_MOUNT` - USB mount point
- `BACKUP_FILES` - Files to backup

## Backup Scope
- `episodic.jsonl` - Episodic memory/logs
- `events.jsonl` - Events log
- `facts.json` - Facts database
- `health_memory.json` - Health memory

## Behavior
1. Entries older than 30 days are archived to USB
2. Recent entries stay on phone for fast access
3. Archived entries remain searchable via `search` command
4. Can retrieve specific days from archive

## Retrieval Priority
1. Recent on-phone memory (default)
2. USB archive (via `search` or `retrieve`)
