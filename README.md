# Reaper

Orphan process hunter for Claude Code. Finds and terminates stale Claude Code processes that remain running after sessions end.

## Installation

```bash
cd reaper
uv sync
```

## Usage

### List processes

```bash
uv run reaper list
```

Shows all Claude Code processes with status:
- **current**: Your active session
- **active**: Attached to a terminal
- **orphan**: No terminal attached (likely stale)

### Hunt orphans

```bash
uv run reaper hunt
```

Terminates orphan processes (those with no terminal attached).

Options:
- `-y, --yes`: Skip confirmation prompt
- `-f, --force`: Use SIGKILL instead of SIGTERM
- `-a, --all`: Kill all non-current processes, not just orphans

### Examples

```bash
# List all Claude processes
uv run reaper list

# Kill orphans with confirmation
uv run reaper hunt

# Kill orphans without confirmation
uv run reaper hunt -y

# Force kill all stale processes
uv run reaper hunt --all --force --yes
```

## Development

```bash
uv sync
uv run pytest
uv run ruff check src tests
uv run mypy src
```
