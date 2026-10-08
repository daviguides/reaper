"""Tests for core functionality."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from reaper.core import (
    _parse_ps_row,
    discover_session_protected_pids,
    has_spare_marker,
    identify_idle_processes,
    identify_orphan_processes,
    identify_stale_processes,
    is_claude_cli,
    is_pid_alive,
    parse_cpu_time,
    process_ancestor_pids,
)
from reaper.models import (
    ProcessInfo,
    calculate_total_memory,
    format_memory_size,
)


@pytest.fixture(autouse=True)
def _no_real_protected_pids():
    """Isolate every test from this machine's real ~/work/projects.

    `identify_orphan_processes`/`identify_stale_processes` default
    to `discover_session_protected_pids()` when `protected_pids`
    isn't passed — without this, existing tests calling them bare
    would depend on whatever's actually running on the machine.
    Tests exercising the session-awareness pass `protected_pids`
    explicitly, overriding this.
    """
    with (
        patch(
            "reaper.core.discover_session_protected_pids",
            return_value=set(),
        ),
        patch("reaper.core.has_spare_marker", return_value=False),
    ):
        yield


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


class TestIsPidAlive:
    """Tests for is_pid_alive."""

    def test_current_process_is_alive(self) -> None:
        import os

        assert is_pid_alive(os.getpid()) is True

    def test_dead_pid_is_not_alive(self) -> None:
        import subprocess

        proc = subprocess.Popen(["true"])
        proc.wait()
        # Give the OS a moment to reap; PID is now free/unassigned
        # to a live process either way.
        assert is_pid_alive(proc.pid) is False

    def test_permission_error_still_counts_as_alive(self) -> None:
        with patch(
            "reaper.core.os.kill",
            side_effect=PermissionError,
        ):
            assert is_pid_alive(1) is True


class TestDiscoverSessionProtectedPids:
    """Tests for discover_session_protected_pids."""

    def test_no_projects_root_returns_empty(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist"
        assert discover_session_protected_pids(missing) == set()

    def test_live_pid_marker_is_protected(self, tmp_path: Path) -> None:
        import os

        marker_dir = (
            tmp_path / "owner" / "repo" / "project" / ".active-sessions"
        )
        marker_dir.mkdir(parents=True)
        (marker_dir / "my-task.yaml").write_text(
            f"task: my-task\nmilestone: ''\npid: {os.getpid()}\n"
            "mode: \"\"\nsession_file: sessions/x.jsonl\n"
            "started: '2026-07-15T00:00:00Z'\n",
        )

        result = discover_session_protected_pids(tmp_path)

        assert result == {os.getpid()}

    def test_dead_pid_marker_is_not_protected(self, tmp_path: Path) -> None:
        import subprocess

        proc = subprocess.Popen(["true"])
        proc.wait()

        marker_dir = (
            tmp_path / "owner" / "repo" / "project" / ".active-sessions"
        )
        marker_dir.mkdir(parents=True)
        (marker_dir / "my-task.yaml").write_text(
            f"task: my-task\npid: {proc.pid}\n",
        )

        result = discover_session_protected_pids(tmp_path)

        assert result == set()

    def test_malformed_marker_ignored(self, tmp_path: Path) -> None:
        marker_dir = (
            tmp_path / "owner" / "repo" / "project" / ".active-sessions"
        )
        marker_dir.mkdir(parents=True)
        (marker_dir / "broken.yaml").write_text("not a pid line at all\n")

        assert discover_session_protected_pids(tmp_path) == set()


class TestProcessAncestorPids:
    """Tests for process_ancestor_pids."""

    def test_walks_up_chain_until_init(self) -> None:
        # 500 -> 400 -> 300 -> init(1)
        responses = iter(["400", "300", "1"])

        def _fake_run(cmd, **kwargs):
            result = MagicMock()
            result.stdout = next(responses)
            return result

        with patch(
            "reaper.core.subprocess.run",
            side_effect=_fake_run,
        ):
            chain = process_ancestor_pids(500)

        assert chain == [500, 400, 300]

    def test_stops_on_empty_ppid(self) -> None:
        result = MagicMock()
        result.stdout = ""
        with patch("reaper.core.subprocess.run", return_value=result):
            chain = process_ancestor_pids(999)
        assert chain == [999]

    def test_stops_on_lookup_failure(self) -> None:
        import subprocess

        with patch(
            "reaper.core.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "ps"),
        ):
            chain = process_ancestor_pids(999)
        assert chain == [999]


class TestClaudeAppExclusion:
    """Claude.app desktop must never be matched as a Claude Code process."""

    def test_parse_ps_row_skips_claude_app(self) -> None:
        line = (
            "12345 1 65536 ?? 10:00 0:05.00 "
            "/Applications/Claude.app/Contents/MacOS/Claude"
        )
        assert _parse_ps_row(line=line, current_pids={1}) is None

    def test_parse_ps_row_skips_claude_app_helper(self) -> None:
        line = (
            "12346 1 32768 ?? 10:00 0:01.00 "
            "/Applications/Claude.app/Contents/Frameworks/"
            "Claude Helper (Renderer).app/Contents/MacOS/"
            "Claude Helper (Renderer)"
        )
        assert _parse_ps_row(line=line, current_pids={1}) is None

    def test_parse_ps_row_keeps_claude_cli(self) -> None:
        line = (
            "54321 900 131072 ttys001 10:00 0:30.00 "
            "claude --dangerously-skip-permissions --model opus"
        )
        result = _parse_ps_row(line=line, current_pids={1})
        assert result is not None
        assert result.pid == 54321
        assert result.terminal == "s001"

    def test_discover_skips_claude_app_in_ps_output(self) -> None:
        ps_output = (
            "12345 1 65536 ?? 10:00 0:05.00 "
            "/Applications/Claude.app/Contents/MacOS/Claude\n"
            "54321 900 131072 ttys001 10:00 0:30.00 "
            "claude --dangerously-skip-permissions\n"
        )
        mock_result = MagicMock()
        mock_result.stdout = ps_output

        with (
            patch("reaper.core.subprocess.run", return_value=mock_result),
            patch("reaper.core.get_current_pids", return_value={1}),
        ):
            from reaper.core import discover_claude_processes

            processes = discover_claude_processes()

        assert len(processes) == 1
        assert processes[0].pid == 54321


class TestClaudeCliMatching:
    """Only the Claude Code CLI is a Claude Code process: matched by
    executable, never by a "claude" substring elsewhere in argv."""

    def test_detached_python_job_under_claude_tmp_is_not_matched(self) -> None:
        # The eval runs that reaper killed every 15 min (exit 144).
        line = (
            "55599 1 900000 ?? 10:46 3:00.00 "
            "/repo/.venv/bin/python -m trybe_assistant.eval run "
            "--out /private/tmp/claude-502/proj/session/scratchpad/bl/x.json"
        )
        assert _parse_ps_row(line=line, current_pids={2}) is None

    def test_bash_tool_shell_of_live_session_is_not_matched(self) -> None:
        line = (
            "56045 15060 2000 ?? 10:46 0:00.03 "
            "/bin/zsh -c source /Users/davi/.claude/shell-snapshots/"
            "snapshot-zsh-1.sh && pytest"
        )
        assert _parse_ps_row(line=line, current_pids={2}) is None

    def test_other_tool_with_claude_model_flag_is_not_matched(self) -> None:
        assert not is_claude_cli(
            "/opt/homebrew/bin/llm --model claude-opus-5-5 prompt"
        )

    def test_claude_by_absolute_path_is_matched(self) -> None:
        assert is_claude_cli("/Users/davi/.local/bin/claude -p hi")

    def test_node_hosted_claude_code_is_matched(self) -> None:
        assert is_claude_cli(
            "node /usr/local/lib/node_modules/@anthropic-ai/"
            "claude-code/cli.js --resume abc"
        )

    def test_node_running_other_script_is_not_matched(self) -> None:
        assert not is_claude_cli("node /tmp/claude-502/server.js")


class TestOrphanRequiresDeadParent:
    """No TTY alone is not orphanhood: the parent must be gone."""

    def test_stale_orphan_claude_is_reaped(self) -> None:
        line = "700 1 300000 ?? 09:00 0:10.00 claude --resume abc"
        process = _parse_ps_row(line=line, current_pids={2})
        assert process is not None and process.is_orphan
        result = identify_orphan_processes(
            processes=[process], protected_pids=set(),
        )
        assert [p.pid for p in result] == [700]

    def test_claude_p_under_live_script_is_spared(self) -> None:
        # `claude -p` run by a live script: no TTY, parent alive.
        line = "701 650 200000 ?? 09:00 0:10.00 claude -p summarize"
        process = _parse_ps_row(line=line, current_pids={2})
        assert process is not None and not process.is_orphan
        assert identify_orphan_processes(
            processes=[process], protected_pids=set(),
        ) == []

    def test_active_claude_with_terminal_is_spared(self) -> None:
        line = "702 600 400000 ttys004 09:00 9:10.00 claude --resume x"
        process = _parse_ps_row(line=line, current_pids={2})
        assert process is not None and not process.is_orphan
        assert identify_orphan_processes(
            processes=[process], protected_pids=set(),
        ) == []

    def test_ancestor_session_is_current(self) -> None:
        line = "703 1 400000 ?? 09:00 1:00.00 claude --resume x"
        process = _parse_ps_row(line=line, current_pids={9, 703})
        assert process is not None and process.is_current
        assert identify_orphan_processes(
            processes=[process], protected_pids=set(),
        ) == []


class TestSpareOptOut:
    """`REAPER_SPARE=1` in the process environment is always honoured."""

    def test_opted_out_orphan_is_spared(self) -> None:
        processes = [
            _create_process(pid=200, is_orphan=True),
            _create_process(pid=300, is_orphan=True),
        ]
        with patch(
            "reaper.core.has_spare_marker",
            side_effect=lambda pid: pid == 200,
        ):
            result = identify_orphan_processes(
                processes=processes, protected_pids=set(),
            )
        assert [p.pid for p in result] == [300]

    def test_opt_out_also_holds_for_all_mode(self) -> None:
        processes = [
            _create_process(pid=200, is_orphan=False),
            _create_process(pid=300, is_orphan=False),
        ]
        with patch(
            "reaper.core.has_spare_marker",
            side_effect=lambda pid: pid == 300,
        ):
            result = identify_stale_processes(
                processes=processes, protected_pids=set(),
            )
        assert [p.pid for p in result] == [200]

    def test_has_spare_marker_reads_process_environment(self) -> None:
        result = MagicMock()
        result.stdout = "claude --resume x PATH=/bin REAPER_SPARE=1 HOME=/u"
        with patch("reaper.core.subprocess.run", return_value=result):
            assert has_spare_marker(123)
        result.stdout = "claude --resume x PATH=/bin HOME=/u"
        with patch("reaper.core.subprocess.run", return_value=result):
            assert not has_spare_marker(123)


class TestAllModeSemantics:
    """`--all` still means every non-current Claude CLI process."""

    def test_all_mode_includes_attached_and_orphan(self) -> None:
        processes = [
            _create_process(pid=100, is_current=True),
            _create_process(pid=200, is_orphan=True),
            _create_process(pid=300, is_orphan=False),
        ]
        result = identify_stale_processes(
            processes=processes, protected_pids=set(),
        )
        assert [p.pid for p in result] == [200, 300]


class TestIdleSampling:
    """An orphan still burning CPU is not stale yet."""

    def test_busy_orphan_is_spared_idle_one_is_kept(self) -> None:
        processes = [
            _create_process(pid=200, is_orphan=True),
            _create_process(pid=300, is_orphan=True),
        ]
        samples = iter([{200: 10.0, 300: 5.0}, {200: 12.5, 300: 5.0}])
        with patch(
            "reaper.core.read_cpu_seconds",
            side_effect=lambda pids: next(samples),
        ):
            result = identify_idle_processes(
                processes=processes, sleep=lambda s: None,
            )
        assert [p.pid for p in result] == [300]

    def test_process_gone_during_sampling_is_dropped(self) -> None:
        processes = [_create_process(pid=200, is_orphan=True)]
        samples = iter([{200: 1.0}, {}])
        with patch(
            "reaper.core.read_cpu_seconds",
            side_effect=lambda pids: next(samples),
        ):
            assert identify_idle_processes(
                processes=processes, sleep=lambda s: None,
            ) == []

    def test_parse_cpu_time_formats(self) -> None:
        assert parse_cpu_time("0:05.50") == 5.5
        assert parse_cpu_time("1:02:03.00") == 3723.0
        assert parse_cpu_time("2-01:00:00.00") == 2 * 86400 + 3600.0


class TestOrphanDetectionRespectsScheduler:
    """Scheduler-dispatched processes must never be treated as orphan/stale,
    even though they legitimately have no TTY."""

    def test_protected_ancestor_excludes_from_orphans(self) -> None:
        processes = [
            _create_process(pid=100, is_current=True),
            _create_process(pid=200, is_orphan=True),  # scheduler-dispatched
            _create_process(pid=300, is_orphan=True),  # genuine orphan
        ]

        def _fake_ancestors(pid, max_depth=32):
            if pid == 200:
                return [200, 250, 999]  # 999 = protected foreman PID
            return [pid]

        with patch(
            "reaper.core.process_ancestor_pids",
            side_effect=_fake_ancestors,
        ):
            result = identify_orphan_processes(
                processes=processes,
                protected_pids={999},
            )

        assert [p.pid for p in result] == [300]

    def test_no_protected_pids_keeps_prior_behavior(self) -> None:
        processes = [
            _create_process(pid=200, is_orphan=True),
        ]
        result = identify_orphan_processes(
            processes=processes,
            protected_pids=set(),
        )
        assert [p.pid for p in result] == [200]

    def test_stale_processes_also_respect_protection(self) -> None:
        processes = [
            _create_process(pid=200, is_orphan=True),
            _create_process(pid=300, is_orphan=False),
        ]

        def _fake_ancestors(pid, max_depth=32):
            if pid == 200:
                return [200, 999]
            return [pid]

        with patch(
            "reaper.core.process_ancestor_pids",
            side_effect=_fake_ancestors,
        ):
            result = identify_stale_processes(
                processes=processes,
                protected_pids={999},
            )

        assert [p.pid for p in result] == [300]
