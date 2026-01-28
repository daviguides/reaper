"""CLI interface for Reaper using Typer and Rich."""

import typer
from rich.console import Console
from rich.table import Table

from reaper import __version__
from reaper.core import (
    discover_claude_processes,
    identify_orphan_processes,
    identify_stale_processes,
    terminate_processes,
)
from reaper.models import (
    ProcessInfo,
    calculate_total_memory,
    format_memory_size,
)

app = typer.Typer(
    name="reaper",
    help="Orphan process hunter - finds and kills stale Claude Code processes",
    no_args_is_help=True,
)
console = Console()


def _create_process_table(
    processes: list[ProcessInfo],
    title: str,
) -> Table:
    """Create a Rich table for process display."""
    table = Table(title=title)

    table.add_column("PID", justify="right", style="cyan")
    table.add_column("Terminal", style="magenta")
    table.add_column("Started", style="green")
    table.add_column("CPU Time", style="yellow")
    table.add_column("Memory", justify="right", style="red")
    table.add_column("Status", style="bold")

    for p in processes:
        status = _get_status_display(process=p)
        table.add_row(
            str(p.pid),
            p.terminal,
            p.start_time,
            p.cpu_time,
            p.memory_display,
            status,
        )

    return table


def _get_status_display(process: ProcessInfo) -> str:
    """Get display string for process status."""
    if process.is_current:
        return "[green]current[/green]"
    if process.is_orphan:
        return "[red]orphan[/red]"
    return "[yellow]active[/yellow]"


@app.command(name="list")
def list_processes() -> None:
    """List all Claude Code processes."""
    processes = discover_claude_processes()

    if not processes:
        console.print("[yellow]No Claude Code processes found.[/yellow]")
        return

    table = _create_process_table(
        processes=processes,
        title="Claude Code Processes",
    )
    console.print(table)

    orphans = [p for p in processes if p.is_orphan]
    if orphans:
        total_memory = calculate_total_memory(processes=orphans)
        memory_str = format_memory_size(total_memory)
        console.print(
            f"\n[red]Found {len(orphans)} orphan process(es) "
            f"consuming {memory_str}[/red]"
        )
        console.print(
            "Run [bold]reaper hunt[/bold] to terminate and free memory."
        )


@app.command()
def hunt(
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Use SIGKILL instead of SIGTERM",
    ),
    all_stale: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Kill all non-current processes, not just orphans",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt",
    ),
) -> None:
    """Terminate orphan Claude Code processes."""
    processes = discover_claude_processes()

    if not processes:
        console.print("[yellow]No Claude Code processes found.[/yellow]")
        return

    if all_stale:
        targets = identify_stale_processes(processes=processes)
        target_type = "stale"
    else:
        targets = identify_orphan_processes(processes=processes)
        target_type = "orphan"

    if not targets:
        console.print(
            f"[green]No {target_type} processes to terminate.[/green]"
        )
        return

    total_memory = calculate_total_memory(processes=targets)
    memory_str = format_memory_size(total_memory)

    table = _create_process_table(
        processes=targets,
        title=f"Processes to Terminate ({len(targets)} {target_type})",
    )
    console.print(table)
    console.print(f"\n[bold]Total memory to free: {memory_str}[/bold]")

    if not yes:
        confirmed = typer.confirm(
            f"\nTerminate {len(targets)} process(es)?",
            default=False,
        )
        if not confirmed:
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit(code=0)

    signal_type = "SIGKILL" if force else "SIGTERM"
    console.print(f"\n[bold]Sending {signal_type}...[/bold]")

    successful, failed = terminate_processes(
        processes=targets,
        force=force,
    )

    if successful:
        freed_memory = sum(
            p.memory_kb for p in targets if p.pid in successful
        )
        freed_str = format_memory_size(freed_memory)
        console.print(
            f"[green]Terminated {len(successful)} process(es): "
            f"{', '.join(map(str, successful))}[/green]"
        )
        console.print(f"[green]Freed {freed_str} of RAM[/green]")

    if failed:
        console.print(
            f"[red]Failed to terminate {len(failed)} process(es): "
            f"{', '.join(map(str, failed))}[/red]"
        )
        raise typer.Exit(code=1)


@app.command()
def version() -> None:
    """Show version information."""
    console.print(f"[bold]reaper[/bold] version {__version__}")


if __name__ == "__main__":
    app()
