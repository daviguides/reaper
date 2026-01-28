# Reaper - Context for Claude

## Purpose

Orphan process hunter for Claude Code. Finds and terminates stale Claude Code processes that remain running after sessions end, freeing up RAM.

## Installation

```bash
uv tool install -e ~/work/sources/tools/reaper
```

After installation, use directly: `reaper <command>`

## Commands

| Command | Description |
|---------|-------------|
| `reaper list` | List all Claude processes with memory usage |
| `reaper hunt` | Terminate orphan processes |
| `reaper hunt -y` | Skip confirmation |
| `reaper hunt -f` | Force SIGKILL instead of SIGTERM |
| `reaper hunt -a` | Kill all non-current processes |
| `reaper version` | Show version |

## Usage Examples

```bash
# List processes and memory consumption
reaper list

# Kill orphans with confirmation
reaper hunt

# Kill orphans without confirmation
reaper hunt -y

# Force kill all stale processes
reaper hunt --all --force --yes
```

## Output

```
                    Claude Code Processes
┏━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━┓
┃   PID ┃ Terminal ┃ Started ┃ CPU Time ┃   Memory ┃ Status ┃
┡━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━┩
│ 53203 │ s001     │ 11:43   │ 1:27.05  │ 454.3 MB │ active │
│ 61140 │ ??       │ 11:55   │ 0:00.02  │   1.3 MB │ orphan │
└───────┴──────────┴─────────┴──────────┴──────────┴────────┘

Found 1 orphan process(es) consuming 1.3 MB
```

## Process Status

| Status | Description |
|--------|-------------|
| `current` | Your active Claude session |
| `active` | Attached to a terminal |
| `orphan` | No terminal attached (stale) |

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.13 |
| CLI | Typer |
| Output | Rich |

## Development

```bash
cd ~/work/sources/tools/reaper
uv sync
make test    # Run tests
make check   # Lint + types
```
