"""Data models for process representation."""

from dataclasses import dataclass


@dataclass
class ProcessInfo:
    """Information about a running process."""

    pid: int
    command: str
    terminal: str
    start_time: str
    cpu_time: str
    memory_kb: int
    is_orphan: bool
    is_current: bool

    @property
    def age_display(self) -> str:
        """Return human-readable age description."""
        if self.is_current:
            return "current session"
        if self.is_orphan:
            return f"orphan (started {self.start_time})"
        return f"active (started {self.start_time})"

    @property
    def memory_display(self) -> str:
        """Return human-readable memory size."""
        return format_memory_size(self.memory_kb)


def format_memory_size(kb: int) -> str:
    """Format memory size in human-readable units.

    Args:
        kb: Memory size in kilobytes.

    Returns:
        Formatted string with appropriate unit (KB, MB, GB).
    """
    if kb < 1024:
        return f"{kb} KB"
    if kb < 1024 * 1024:
        return f"{kb / 1024:.1f} MB"
    return f"{kb / (1024 * 1024):.2f} GB"


def calculate_total_memory(processes: list[ProcessInfo]) -> int:
    """Calculate total memory usage of processes.

    Args:
        processes: List of processes.

    Returns:
        Total memory in kilobytes.
    """
    return sum(p.memory_kb for p in processes)
