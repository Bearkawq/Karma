# External Media Karma Recovery Report
**Date**: 2026-03-24  
**System**: Pop!_OS Live Session

---

## External Media Discovered

| Device | Partition | Size | Filesystem | Label | Mounted |
|--------|-----------|------|------------|-------|---------|
| sdb | sdb1 | 50MB | vfat | FD-SETUP | No (DOS boot files only) |
| sdb | sdb2 | 238.2GB | vfat | (none) | No (single Inspiron exe) |
| sdc | sdc1 | 119.1GB | exfat | (none) | **Yes** - 21 karma-related files |

**Note**: Internal Windows partition (sda3) was explicitly excluded per mission rules.

---

## Important Files Found on SDC1

All files were copied read-only from external media to `/home/mikoleye/recovery_found/`:

### Karma Archives (tar.gz)
| File | Size | Date |
|------|------|------|
| Karma-v3.4.2.tar.gz | 15.2MB | (older) |
| Karma-v3.8.0.tar.gz | 15.2MB | (older) |
| Karma-v3.8.1.tar.gz | 15.2MB | (older) |
| karma_v3.8.6_2026-03-19.tar.gz | 724KB | 2026-03-19 |

### Karma Zips
- karma-full.zip (1.1MB)
- karma_v3.8.6_2026-03-19.tar.gz (724KB)
- Multiple patched versions (v3.1.0 through v3.3.5)

---

## Karma Candidates Found & Ranked

| Candidate | Version | Files | Size | Last Modified | Rank |
|-----------|---------|-------|------|---------------|------|
| karma_v3.8.1 | 3.8.1 | 1657 | 86MB | 2026-03-15 | **#1 BEST** |
| karma_v3.8.0 | 3.8.0 | 1655 | 86MB | 2026-03-15 | #2 |
| karma (from v3.8.6 file) | 3.8.0 | 208 | 3.6MB | 2026-03-18 | #3 (incomplete) |
| karma_v3.4.2 | 3.4.2 | 1655 | 86MB | (older) | #4 |

### Ranking Logic

1. **Completeness**: Candidate has 17 directories vs only 17 in the incomplete one
2. **File count**: v3.8.1 has 1657 files (most complete)
3. **Version**: v3.8.1 is highest version number
4. **Documentation**: Includes COMPLETION_REPORT_3_9_0.md showing v3.9.0 development progress
5. **Architecture**: Includes routing lanes, safe mode, unified API schema

### Why karma_v3.8.1 Won

- Highest version (3.8.1)
- Most complete (1657 files, 86MB)
- Contains v3.9.0 development progress (COMPLETION_REPORT_3_9_0.md)
- Includes critical bug fixes for natural language misrouting
- Has routing lanes architecture (CHAT, COMMAND, MEMORY, LEARN, TOOL)
- Includes safe mode feature

---

## Winner Selected

**Winner**: `karma_v3.8.1` (from Karma-v3.8.1.tar.gz)

**Promoted to**: `/home/mikoleye/karma`

### Validation Results
- Directory structure: Complete (17 directories)
- Key modules present: agent/, agents/, core/, data/, models/, navigator/, research/, storage/, tests/, ui/
- Version declared: 3.8.1 (config.json shows 3.8.6)
- AGENTS.md present: Yes
- Git metadata: No (no .git directory)
- Smoke test: Not run (would need pytest installation)

---

## Live Karma Promotion

**Was there an existing /home/mikoleye/karma?** No

**Action taken**: Created `/home/mikoleye/karma` from best candidate

**Backup created**: No backup needed (no existing karma to backup)

**Staging path**: `/home/mikoleye/recovery_candidates/karma_best/`

---

## OpenCode/Config/Prompt Items

**Found on external media**: None

**Existing in /home/mikoleye/.opencode/**:
- skills/opencode-memory/
- skills/opencode-ops/
- skills/opencode-resume/
- bin/ directory

Note: External media contained `.opencode/` in karma repo but no standalone opencode configurations.

---

## Commands Run

```bash
# External media discovery
lsblk -f -o NAME,FSTYPE,LABEL,UUID,SIZE,MOUNTPOINT,MODEL

# Mount external drives using Docker privileged container
docker run --rm -i --privileged --device=/dev/sdb1:/dev/sdb1 ... ubuntu:24.04

# List drive contents
ls -la /mnt/sdc1/

# Copy karma files to recovery
cp /mnt/sdc1/*.tar.gz /home/mikoleye/recovery_found/

# Extract and compare candidates
tar -xzf Karma-v3.8.1.tar.gz -C /home/mikoleye/recovery_candidates/

# Compare candidates
ls -la karma_v3.8.1/ | grep "^d"

# Promote winner
cp -a /home/mikoleye/recovery_candidates/karma_v3.8.1 /home/mikoleye/karma
```

---

## Final Paths

| Item | Path |
|------|------|
| Recovered Karma | `/home/mikoleye/karma/` |
| Best candidate staging | `/home/mikoleye/recovery_candidates/karma_best/` |
| All karma archives | `/home/mikoleye/recovery_found/` |
| This report | `/home/mikoleye/EXTERNAL_MEDIA_KARMA_RECOVERY_REPORT.md` |

---

## Unresolved Uncertainties

1. **Version mismatch**: karma_version.py says 3.8.1, config.json says 3.8.6, COMPLETION_REPORT says 3.9.0
2. **Git history**: No .git directory - cannot verify commit history
3. **Smoke test**: Not executed - would require installing pytest/dependencies
4. **Missing live repo**: Original karma was not present - cannot compare before/after

---

## Recommended Next Actions

1. Install dependencies and run: `cd /home/mikoleye/karma && python3 -m pytest tests/ -q`
2. Update karma_version.py to match config.json (3.8.6) or COMPLETION_REPORT (3.9.0)
3. Review AGENTS.md for operational rules
4. Consider initializing git repo: `cd /home/mikoleye/karma && git init && git add . && git commit -m "Recovered from external media"`
