"""Core business logic for process discovery and termination."""

import os
import re
import signal
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from reaper.models import ProcessInfo

CLAUDE_EXECUTABLE = "claude"
JS_RUNTIMES = ("node", "bun")
CLAUDE_CODE_PACKAGE_MARKER = "claude-code/"
CLAUDE_APP_MARKERS = (".app/contents/", "claude.app")
SPARE_ENV_MARKER = "REAPER_SPARE=1"
PROJECTS_ROOT = Path.home() / "work" / "projects"
MAX_ANCESTOR_DEPTH = 32
INIT_PID = 1
IDLE_SAMPLE_SECONDS = 2.0
IDLE_CPU_TOLERANCE_SECONDS = 0.05


def get_current_pids() -> set[int]:
    """PIDs that belong to the invocation running reaper right now.

    reaper runs under a shell spawned by a Claude Code session (or by
    cron), so the "current session" is not only the direct parent: it
    is any `claude` among our ancestors. Every ancestor is excluded.
    """
    return set(process_ancestor_pids(os.getpid()))


def is_claude_cli(args: str) -> bool:
    """Whether a command line is the Claude Code CLI itself.

    Matching is by executable only: argv[0] named `claude`, or a JS
    runtime running the `@anthropic-ai/claude-code` package. A path
    containing "claude" anywhere else in argv (the session's tmp dir,
    `~/.claude/shell-snapshots`, a `--model claude-...` flag of an
    unrelated tool) never makes a process a Claude Code process.

    Args:
        args: Full command line (argv joined by spaces).

    Returns:
        True only for the Claude Code CLI.
    """
    tokens = args.split()
    if not tokens:
        return False

    executable = tokens[0].lower()
    if any(marker in executable for marker in CLAUDE_APP_MARKERS):
        return False

    name = Path(executable).name
    if name == CLAUDE_EXECUTABLE:
        return True

    if name in JS_RUNTIMES and len(tokens) > 1:
        return CLAUDE_CODE_PACKAGE_MARKER in tokens[1].lower()

    return False


def discover_claude_processes() -> list[ProcessInfo]:
    """Find all running Claude Code CLI processes.

    Returns:
        List of ProcessInfo objects for each Claude process found.

    Raises:
        RuntimeError: If process discovery fails.
    """
    try:
        result = subprocess.run(
            [
                "ps",
                "-axww",
                "-o",
                "pid=,ppid=,rss=,tty=,start=,time=,args=",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to list processes: {e}") from e

    current_pids = get_current_pids()
    processes: list[ProcessInfo] = []

    for line in result.stdout.splitlines():
        process = _parse_ps_row(line=line, current_pids=current_pids)
        if process:
            processes.append(process)

    return sorted(processes, key=lambda p: p.pid)


def _parse_ps_row(
    line: str,
    current_pids: set[int],
) -> ProcessInfo | None:
    """Parse one row of `ps -o pid=,ppid=,rss=,tty=,start=,time=,args=`.

    A process is an orphan only when both hold: no controlling
    terminal, and its parent is gone (re-parented to init/launchd).
    A `claude -p` run by a live script has no TTY either, but its
    parent still owns it.

    Args:
        line: Single row of ps output.
        current_pids: PIDs of the invocation running reaper.

    Returns:
        ProcessInfo if the row is the Claude Code CLI, None otherwise.
    """
    parts = line.split(maxsplit=6)
    if len(parts) < 7:
        return None

    try:
        pid = int(parts[0])
        ppid = int(parts[1])
        memory_kb = int(parts[2])
    except ValueError:
        return None

    terminal = _short_terminal(parts[3])
    start_time = parts[4]
    cpu_time = parts[5]
    command = parts[6]

    if not is_claude_cli(command):
        return None

    return ProcessInfo(
        pid=pid,
        command=command,
        terminal=terminal,
        start_time=start_time,
        cpu_time=cpu_time,
        memory_kb=memory_kb,
        is_orphan=terminal == "??" and ppid == INIT_PID,
        is_current=pid in current_pids,
        ppid=ppid,
    )


def _short_terminal(tty: str) -> str:
    """Render `ttys001` as `s001`, like `ps aux` does."""
    if tty.startswith("tty"):
        return tty[3:]
    return tty


def is_pid_alive(pid: int) -> bool:
    """Check whether a PID currently refers to a live process.

    `os.kill(pid, 0)` sends no signal — it only probes existence.

    Args:
        pid: Process ID to check.

    Returns:
        True if the process exists (even if we lack permission to
        signal it — existence and permission are orthogonal).
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def discover_session_protected_pids(
    projects_root: Path | None = None,
) -> set[int]:
    """PIDs of `foreman` processes with a live session marker.

    Reads foreman's `.active-sessions/<task>.yaml` markers directly
    from disk, across every project directory — reaper has no
    dependency on the orchestration packages (separate repos,
    read the on-disk contract instead). Each marker is written by
    `foreman.core.events.EventEmitter` at session start (`pid:
    {os.getpid()}`, the foreman process's own PID) and removed at
    session end.

    A marker only protects when its recorded PID is genuinely
    alive right now — one left behind by a process that crashed
    without cleanup (the exact scenario this whole investigation
    started from) protects nothing; that process is a real orphan.

    Args:
        projects_root: Override for `~/work/projects` (tests).

    Returns:
        Set of live foreman PIDs found in active-session markers.
    """
    root = projects_root or PROJECTS_ROOT
    protected: set[int] = set()
    if not root.is_dir():
        return protected

    for marker in root.glob("*/*/*/.active-sessions/*.yaml"):
        try:
            text = marker.read_text()
        except OSError:
            continue
        match = re.search(r"^pid:\s*(\d+)", text, re.MULTILINE)
        if not match:
            continue
        pid = int(match.group(1))
        if is_pid_alive(pid):
            protected.add(pid)

    return protected


def process_ancestor_pids(
    pid: int,
    max_depth: int = MAX_ANCESTOR_DEPTH,
) -> list[int]:
    """The PID plus every ancestor up the process tree.

    scheduler-dispatched `claude` processes are grandchildren of the
    `foreman` process the active-session marker records (queue →
    foreman → claude SDK → claude CLI) — checking the PID alone
    against the protected set would never match; the ancestor
    chain is what needs checking.

    Args:
        pid: Starting process ID.
        max_depth: Safety cap against a cycle/misparse looping.

    Returns:
        [pid, parent, grandparent, ...] stopping at init or on
        lookup failure.
    """
    chain = [pid]
    current = pid
    for _ in range(max_depth):
        try:
            result = subprocess.run(
                ["ps", "-o", "ppid=", "-p", str(current)],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError:
            break
        ppid_text = result.stdout.strip()
        if not ppid_text:
            break
        try:
            ppid = int(ppid_text)
        except ValueError:
            break
        if ppid <= 1 or ppid == current:
            break
        chain.append(ppid)
        current = ppid
    return chain


def has_spare_marker(pid: int) -> bool:
    """Whether a process opted out of reaping with `REAPER_SPARE=1`.

    Reads the process environment through `ps -E`, which macOS allows
    for processes of the same user. Launch a session or job with
    `REAPER_SPARE=1 claude ...` to keep reaper away from it.

    Args:
        pid: Process ID to inspect.

    Returns:
        True if `REAPER_SPARE=1` is in the process environment.
    """
    try:
        result = subprocess.run(
            ["ps", "-E", "-ww", "-o", "command=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return False
    return SPARE_ENV_MARKER in result.stdout.split()


def _without_spared(
    processes: list[ProcessInfo],
    protected_pids: set[int],
) -> list[ProcessInfo]:
    """Drop opted-out processes and anything a live session supervises."""
    kept = [p for p in processes if not has_spare_marker(p.pid)]
    if not protected_pids:
        return kept
    return [
        p for p in kept
        if not protected_pids.intersection(process_ancestor_pids(p.pid))
    ]


def identify_orphan_processes(
    processes: list[ProcessInfo],
    protected_pids: set[int] | None = None,
) -> list[ProcessInfo]:
    """Filter processes to find orphans.

    Args:
        processes: List of all Claude processes.
        protected_pids: Live foreman PIDs to never treat as
            orphaned, regardless of TTY — a queue-dispatched
            `claude` process legitimately has none. Defaults to
            `discover_session_protected_pids()`; pass an explicit
            empty set to disable protection entirely.

    Returns:
        List of orphan processes (excluding current session, opted-out
        processes and anything the scheduler supervises).
    """
    if protected_pids is None:
        protected_pids = discover_session_protected_pids()

    candidates = [
        p for p in processes
        if p.is_orphan and not p.is_current
    ]
    return _without_spared(candidates, protected_pids)


def identify_stale_processes(
    processes: list[ProcessInfo],
    exclude_current: bool = True,
    protected_pids: set[int] | None = None,
) -> list[ProcessInfo]:
    """Find all non-current Claude processes.

    Args:
        processes: List of all Claude processes.
        exclude_current: Whether to exclude current session.
        protected_pids: Live foreman PIDs to never treat as stale —
            see `identify_orphan_processes`. Defaults to
            `discover_session_protected_pids()`.

    Returns:
        List of stale processes.
    """
    candidates = (
        [p for p in processes if not p.is_current]
        if exclude_current
        else processes
    )

    if protected_pids is None:
        protected_pids = discover_session_protected_pids()
    return _without_spared(candidates, protected_pids)


def read_cpu_seconds(pids: list[int]) -> dict[int, float]:
    """Accumulated CPU seconds per PID, from `ps -o time=`."""
    if not pids:
        return {}
    try:
        result = subprocess.run(
            ["ps", "-o", "pid=,time=", "-p", ",".join(map(str, pids))],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return {}

    seconds: dict[int, float] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            seconds[int(parts[0])] = parse_cpu_time(parts[1])
        except ValueError:
            continue
    return seconds


def parse_cpu_time(text: str) -> float:
    """Parse ps cumulative time (`[[dd-]hh:]mm:ss.cc`) into seconds."""
    days = 0
    if "-" in text:
        day_text, text = text.split("-", 1)
        days = int(day_text)
    total = 0.0
    for part in text.split(":"):
        total = total * 60 + float(part)
    return days * 86400 + total


def identify_idle_processes(
    processes: list[ProcessInfo],
    window_seconds: float = IDLE_SAMPLE_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> list[ProcessInfo]:
    """Keep only processes that burned no CPU over a sampling window.

    An orphan that is still working (a `claude -p` whose launcher
    exited, still streaming) is not stale yet.
    """
    if not processes:
        return []
    pids = [p.pid for p in processes]
    before = read_cpu_seconds(pids)
    sleep(window_seconds)
    after = read_cpu_seconds(pids)
    return [
        p for p in processes
        if p.pid in before
        and p.pid in after
        and after[p.pid] - before[p.pid] <= IDLE_CPU_TOLERANCE_SECONDS
    ]


def terminate_process(
    pid: int,
    force: bool = False,
) -> bool:
    """Terminate a process by PID.

    Args:
        pid: Process ID to terminate.
        force: Use SIGKILL instead of SIGTERM.

    Returns:
        True if process was terminated successfully.

    Raises:
        PermissionError: If lacking permission to terminate.
        ProcessLookupError: If process no longer exists.
    """
    sig = signal.SIGKILL if force else signal.SIGTERM

    try:
        os.kill(pid, sig)
        return True
    except ProcessLookupError:
        return True
    except PermissionError as e:
        raise PermissionError(
            f"Permission denied to terminate PID {pid}"
        ) from e


def terminate_processes(
    processes: list[ProcessInfo],
    force: bool = False,
) -> tuple[list[int], list[int]]:
    """Terminate multiple processes.

    Args:
        processes: List of processes to terminate.
        force: Use SIGKILL instead of SIGTERM.

    Returns:
        Tuple of (successful_pids, failed_pids).
    """
    successful: list[int] = []
    failed: list[int] = []

    for process in processes:
        try:
            if terminate_process(pid=process.pid, force=force):
                successful.append(process.pid)
            else:
                failed.append(process.pid)
        except PermissionError:
            failed.append(process.pid)

    return successful, failed
