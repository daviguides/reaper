"""Core business logic for process discovery and termination."""

import os
import re
import signal
import subprocess
from pathlib import Path

from reaper.models import ProcessInfo

CLAUDE_PROCESS_NAME = "claude"
CLAUDE_APP_MARKERS = (".app/contents/", "claude.app")
PROJECTS_ROOT = Path.home() / "work" / "projects"
MAX_ANCESTOR_DEPTH = 32


def get_current_pid() -> int:
    """Get the PID of the current Claude Code process."""
    return os.getppid()


def discover_claude_processes() -> list[ProcessInfo]:
    """Find all running Claude Code processes.

    Returns:
        List of ProcessInfo objects for each Claude process found.

    Raises:
        RuntimeError: If process discovery fails.
    """
    try:
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to list processes: {e}") from e

    current_pid = get_current_pid()
    processes: list[ProcessInfo] = []

    for line in result.stdout.splitlines()[1:]:
        line_lower = line.lower()

        if CLAUDE_PROCESS_NAME not in line_lower:
            continue

        if "grep" in line_lower:
            continue

        if any(marker in line_lower for marker in CLAUDE_APP_MARKERS):
            continue

        process = _parse_ps_line(line=line, current_pid=current_pid)
        if process:
            processes.append(process)

    return sorted(processes, key=lambda p: p.pid)


def _parse_ps_line(
    line: str,
    current_pid: int,
) -> ProcessInfo | None:
    """Parse a line from ps aux output.

    ps aux columns: USER PID %CPU %MEM VSZ RSS TTY STAT START TIME COMMAND

    Args:
        line: Single line from ps aux output.
        current_pid: PID of the current process.

    Returns:
        ProcessInfo if line represents a Claude process, None otherwise.
    """
    parts = line.split()
    if len(parts) < 11:
        return None

    try:
        pid = int(parts[1])
        memory_kb = int(parts[5])  # RSS column (resident set size)
    except ValueError:
        return None

    terminal = parts[6]
    start_time = parts[8]
    cpu_time = parts[9]
    command = " ".join(parts[10:])

    command_lower = command.lower()
    if CLAUDE_PROCESS_NAME not in command_lower:
        return None

    if any(marker in command_lower for marker in CLAUDE_APP_MARKERS):
        return None

    is_orphan = terminal == "??"
    is_current = pid == current_pid

    return ProcessInfo(
        pid=pid,
        command=command,
        terminal=terminal,
        start_time=start_time,
        cpu_time=cpu_time,
        memory_kb=memory_kb,
        is_orphan=is_orphan,
        is_current=is_current,
    )


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


def identify_orphan_processes(
    processes: list[ProcessInfo],
    protected_pids: set[int] | None = None,
) -> list[ProcessInfo]:
    """Filter processes to find orphans (no terminal attached).

    Args:
        processes: List of all Claude processes.
        protected_pids: Live foreman PIDs to never treat as
            orphaned, regardless of TTY — a queue-dispatched
            `claude` process legitimately has none. Defaults to
            `discover_session_protected_pids()`; pass an explicit
            empty set to disable protection entirely.

    Returns:
        List of orphan processes (excluding current session and
        anything the scheduler supervises).
    """
    if protected_pids is None:
        protected_pids = discover_session_protected_pids()

    candidates = [
        p for p in processes
        if p.is_orphan and not p.is_current
    ]
    if not protected_pids:
        return candidates

    return [
        p for p in candidates
        if not protected_pids.intersection(
            process_ancestor_pids(p.pid),
        )
    ]


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
    if not protected_pids:
        return candidates

    return [
        p for p in candidates
        if not protected_pids.intersection(
            process_ancestor_pids(p.pid),
        )
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
