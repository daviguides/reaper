"""Core business logic for process discovery and termination."""

import os
import signal
import subprocess

from reaper.models import ProcessInfo

CLAUDE_PROCESS_NAME = "claude"


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
        if CLAUDE_PROCESS_NAME not in line.lower():
            continue

        if "grep" in line.lower():
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

    if CLAUDE_PROCESS_NAME not in command.lower():
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


def identify_orphan_processes(
    processes: list[ProcessInfo],
) -> list[ProcessInfo]:
    """Filter processes to find orphans (no terminal attached).

    Args:
        processes: List of all Claude processes.

    Returns:
        List of orphan processes (excluding current session).
    """
    return [
        p for p in processes
        if p.is_orphan and not p.is_current
    ]


def identify_stale_processes(
    processes: list[ProcessInfo],
    exclude_current: bool = True,
) -> list[ProcessInfo]:
    """Find all non-current Claude processes.

    Args:
        processes: List of all Claude processes.
        exclude_current: Whether to exclude current session.

    Returns:
        List of stale processes.
    """
    if exclude_current:
        return [p for p in processes if not p.is_current]
    return processes


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
