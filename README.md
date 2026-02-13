# Reaper

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> Orphan process hunter for Claude Code. Finds and terminates stale processes that remain running after sessions end, freeing up RAM.

## Installation

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/daviguides/reaper/main/install.sh)"
```

### Manual Installation

```bash
git clone https://github.com/daviguides/reaper.git ~/.local/share/reaper
uv tool install -e ~/.local/share/reaper
```

The installer also sets up a cron job to run `reaper hunt -y` every 15 minutes automatically.

### Updating

Re-run the installer — it pulls latest changes and updates the cron job:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/daviguides/reaper/main/install.sh)"
```

Or manually:

```bash
cd ~/.local/share/reaper && git pull
```

Since the install is editable, pulling new changes is all you need.

## Usage

### List processes

```bash
reaper list
```

Shows all Claude Code processes with status:
- **current**: Your active session
- **active**: Attached to a terminal
- **orphan**: No terminal attached (likely stale)

### Hunt orphans

```bash
reaper hunt
```

Terminates orphan processes (those with no terminal attached).

Options:
- `-y, --yes`: Skip confirmation prompt
- `-f, --force`: Use SIGKILL instead of SIGTERM
- `-a, --all`: Kill all non-current processes, not just orphans

### Examples

```bash
# List all Claude processes
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

## Development

```bash
cd reaper
uv sync
make test    # Run tests
make check   # Lint + types
make format  # Format code
```

## License

MIT License
