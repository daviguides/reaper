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
| `current` | The Claude session running reaper (any ancestor of the invocation) |
| `active` | Attached to a terminal, or its parent is still alive |
| `orphan` | No terminal AND parent gone (PPID 1) |

## What Counts as a Claude Code Process

Only the Claude Code CLI: argv[0] named `claude`, or `node`/`bun` running the
`@anthropic-ai/claude-code` package. Claude.app is excluded. A "claude" substring
elsewhere in argv (the session tmp dir `/private/tmp/claude-<uid>/...`,
`~/.claude/shell-snapshots`, a `--model claude-...` flag) never matches, so jobs
launched from a session (evals, builds, servers, tool shells) are never reaped.

`hunt` kills an orphan only if it is also idle (no CPU progress over a 2s sample).

## Opting Out

Start a process with `REAPER_SPARE=1` in its environment to keep reaper away from
it in every mode, `--all` included (read via `ps -E`, same user only):

```bash
REAPER_SPARE=1 claude -p "long job"
```

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
