"""Tests for core functionality."""

from reaper.core import identify_orphan_processes, identify_stale_processes
from reaper.models import (
    ProcessInfo,
    calculate_total_memory,
    format_memory_size,
)


def _create_process(
    pid: int,
    is_orphan: bool = False,
    is_current: bool = False,
    memory_kb: int = 100000,
) -> ProcessInfo:
    """Create a test ProcessInfo instance."""
    return ProcessInfo(
        pid=pid,
        command="claude --dangerously-skip-permissions",
        terminal="??" if is_orphan else "s001",
        start_time="10:00",
        cpu_time="0:05.00",
        memory_kb=memory_kb,
        is_orphan=is_orphan,
        is_current=is_current,
    )


class TestIdentifyOrphanProcesses:
    """Tests for identify_orphan_processes function."""

    def test_returns_empty_when_no_orphans(self) -> None:
        """Test returns empty list when no orphans exist."""
        processes = [
            _create_process(pid=100, is_current=True),
            _create_process(pid=200, is_orphan=False),
        ]

        result = identify_orphan_processes(processes=processes)

        assert result == []

    def test_finds_orphan_processes(self) -> None:
        """Test identifies orphan processes correctly."""
        processes = [
            _create_process(pid=100, is_current=True),
            _create_process(pid=200, is_orphan=True),
            _create_process(pid=300, is_orphan=True),
        ]

        result = identify_orphan_processes(processes=processes)

        assert len(result) == 2
        assert all(p.is_orphan for p in result)

    def test_excludes_current_even_if_orphan(self) -> None:
        """Test excludes current session even if marked orphan."""
        processes = [
            _create_process(pid=100, is_orphan=True, is_current=True),
            _create_process(pid=200, is_orphan=True),
        ]

        result = identify_orphan_processes(processes=processes)

        assert len(result) == 1
        assert result[0].pid == 200


class TestIdentifyStaleProcesses:
    """Tests for identify_stale_processes function."""

    def test_excludes_current_by_default(self) -> None:
        """Test excludes current process by default."""
        processes = [
            _create_process(pid=100, is_current=True),
            _create_process(pid=200),
            _create_process(pid=300),
        ]

        result = identify_stale_processes(processes=processes)

        assert len(result) == 2
        assert all(not p.is_current for p in result)

    def test_includes_all_when_exclude_current_false(self) -> None:
        """Test includes all processes when exclude_current is False."""
        processes = [
            _create_process(pid=100, is_current=True),
            _create_process(pid=200),
        ]

        result = identify_stale_processes(
            processes=processes,
            exclude_current=False,
        )

        assert len(result) == 2


class TestProcessInfo:
    """Tests for ProcessInfo model."""

    def test_age_display_current_session(self) -> None:
        """Test age display for current session."""
        process = _create_process(pid=100, is_current=True)

        assert process.age_display == "current session"

    def test_age_display_orphan(self) -> None:
        """Test age display for orphan process."""
        process = _create_process(pid=100, is_orphan=True)

        assert "orphan" in process.age_display

    def test_age_display_active(self) -> None:
        """Test age display for active process."""
        process = _create_process(pid=100)

        assert "active" in process.age_display

    def test_memory_display(self) -> None:
        """Test memory display formatting."""
        process = _create_process(pid=100, memory_kb=512000)

        assert "500" in process.memory_display
        assert "MB" in process.memory_display


class TestMemoryFunctions:
    """Tests for memory-related functions."""

    def test_format_memory_size_kb(self) -> None:
        """Test format_memory_size with kilobytes."""
        assert format_memory_size(500) == "500 KB"

    def test_format_memory_size_mb(self) -> None:
        """Test format_memory_size with megabytes."""
        result = format_memory_size(2048)
        assert "MB" in result
        assert "2.0" in result

    def test_format_memory_size_gb(self) -> None:
        """Test format_memory_size with gigabytes."""
        result = format_memory_size(2 * 1024 * 1024)
        assert "GB" in result
        assert "2.00" in result

    def test_calculate_total_memory(self) -> None:
        """Test calculate_total_memory sums correctly."""
        processes = [
            _create_process(pid=100, memory_kb=100000),
            _create_process(pid=200, memory_kb=200000),
            _create_process(pid=300, memory_kb=50000),
        ]

        total = calculate_total_memory(processes=processes)

        assert total == 350000

    def test_calculate_total_memory_empty_list(self) -> None:
        """Test calculate_total_memory with empty list."""
        total = calculate_total_memory(processes=[])

        assert total == 0
