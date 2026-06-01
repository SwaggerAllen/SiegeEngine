"""Command-line query + pipeline interface.

Query commands implement the spec's CLI surface:
    wgtracker list-threads --topic federation --since 2025-10-01
    wgtracker show-thread <thread_id>
    wgtracker recent --topic <topic>
    wgtracker participants --topic <topic>
    wgtracker drafts --topic <topic>
    wgtracker draft <draft_name>
Plus pipeline + budget commands.
"""
from __future__ import annotations

from datetime import UTC, datetime

import typer
from dateutil import parser as dateparser
from rich.console import Console
from rich.table import Table

from . import queries
from .config import get_settings
from .costs import spend_by_stage, total_spend
from .db import session_scope
from .logging_conf import configure_logging
from .pipeline import recategorize_all, run_full_pipeline, seed_topics

app = typer.Typer(help="IETF Working Group Activity Tracker", no_args_is_help=True)
console = Console()


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = dateparser.parse(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


@app.callback()
def _main() -> None:
    configure_logging(get_settings().log_level)


# --------------------------------------------------------------------------- #
# Query commands
# --------------------------------------------------------------------------- #


@app.command("list-threads")
def list_threads(
    topic: str = typer.Option(None),
    working_group: str = typer.Option(None, "--working-group", "--wg"),
    since: str = typer.Option(None),
    until: str = typer.Option(None),
    status: str = typer.Option(None),
    limit: int = typer.Option(50),
) -> None:
    """List threads, filtered by topic / WG / date / status."""
    with session_scope() as s:
        rows = queries.list_threads(
            s,
            topic=topic,
            working_group=working_group,
            since=_parse_date(since),
            until=_parse_date(until),
            status=status,
            limit=limit,
        )
    table = Table(title="Threads")
    for col in ("thread_id", "wg", "subject", "dates", "msgs", "status", "consensus"):
        table.add_column(col, overflow="fold")
    for r in rows:
        table.add_row(
            r["thread_id"],
            r["working_group"],
            r["subject"][:60],
            r["date_range"],
            str(r["message_count"]),
            r["status"] or "-",
            r["consensus_state"] or "-",
        )
    console.print(table)
    console.print(f"[dim]{len(rows)} threads[/dim]")


@app.command("show-thread")
def show_thread(thread_id: str) -> None:
    """Full summary for a thread, including referenced drafts and the source URL."""
    with session_scope() as s:
        d = queries.get_thread_detail(s, thread_id)
    if d is None:
        console.print(f"[red]No thread {thread_id}[/red]")
        raise typer.Exit(1)
    console.print(f"[bold]{d['subject']}[/bold]  ({d['working_group']})")
    console.print(f"[dim]{d['date_range']}  •  {d['message_count']} messages  •  "
                  f"status={d['status']}  •  consensus={d['consensus_state']}[/dim]")
    console.print(f"[blue]Source:[/blue] {d['archive_url']}\n")
    console.print(d["summary"] or "[dim](not yet summarized)[/dim]")
    if d["key_positions"]:
        console.print("\n[bold]Key positions:[/bold]")
        for p in d["key_positions"]:
            console.print(f"  • [{p['holder']}] {p['position']} — {p['context']}")
    if d["topics"]:
        console.print("\n[bold]Topics:[/bold] " +
                      ", ".join(f"{t['topic']}({t['confidence']:.2f})" for t in d["topics"]))
    if d["referenced_drafts"]:
        console.print("\n[bold]Referenced drafts:[/bold]")
        for dr in d["referenced_drafts"]:
            vers = f" {dr['versions_referenced']}" if dr["versions_referenced"] else ""
            console.print(f"  • {dr['draft_name']}{vers} — {dr['title']} ({dr['datatracker_url']})")


@app.command("recent")
def recent(
    topic: str = typer.Option(None),
    working_group: str = typer.Option(None, "--working-group", "--wg"),
    days: int = typer.Option(30),
) -> None:
    """Recent activity (default last 30 days) in a topic / WG."""
    with session_scope() as s:
        rows = queries.recent_activity(s, topic=topic, working_group=working_group, days=days)
    for r in rows:
        console.print(f"[bold]{r['subject']}[/bold] ({r['working_group']}, {r['date_range']})")
        console.print(f"  {r['summary_brief']}")
        console.print(f"  [blue]{r['archive_url']}[/blue]\n")
    console.print(f"[dim]{len(rows)} threads in last {days} days[/dim]")


@app.command("participants")
def participants_cmd(
    topic: str = typer.Option(None),
    working_group: str = typer.Option(None, "--working-group", "--wg"),
    limit: int = typer.Option(25),
) -> None:
    """Most active participants in a topic / WG."""
    with session_scope() as s:
        rows = queries.participants(s, topic=topic, working_group=working_group, limit=limit)
    table = Table(title="Participants")
    table.add_column("messages", justify="right")
    table.add_column("name")
    table.add_column("address")
    for r in rows:
        table.add_row(str(r["message_count"]), r["from_name"] or "-", r["from_address"])
    console.print(table)


@app.command("drafts")
def drafts_cmd(
    topic: str = typer.Option(None),
    working_group: str = typer.Option(None, "--working-group", "--wg"),
    status: str = typer.Option(None),
    referenced_since: str = typer.Option(None),
) -> None:
    """List drafts referenced in discussions (optionally filtered by topic)."""
    with session_scope() as s:
        rows = queries.list_drafts(
            s,
            topic=topic,
            working_group=working_group,
            status=status,
            referenced_since=_parse_date(referenced_since),
        )
    table = Table(title="Drafts")
    table.add_column("threads", justify="right")
    table.add_column("draft")
    table.add_column("ver")
    table.add_column("status")
    table.add_column("title", overflow="fold")
    for r in rows:
        table.add_row(
            str(r["thread_count"]),
            r["draft_name"],
            r["current_version"] or "-",
            (r["status"] or "-")[:20],
            (r["title"] or "-")[:50],
        )
    console.print(table)


@app.command("draft")
def draft_cmd(draft_name: str) -> None:
    """Show draft metadata and threads referencing it."""
    with session_scope() as s:
        d = queries.get_draft(s, draft_name)
    if d is None:
        console.print(f"[red]No draft {draft_name}[/red]")
        raise typer.Exit(1)
    console.print(f"[bold]{d['draft_name']}[/bold] {d['current_version'] or ''} — {d['title']}")
    console.print(f"[dim]status={d['status']}  wg={d['working_group']}  rfc={d['rfc_number']}[/dim]")
    console.print(f"[blue]{d['datatracker_url']}[/blue]")
    if d["abstract"]:
        console.print(f"\n{d['abstract']}\n")
    console.print(f"[bold]Discussed in {len(d['threads'])} threads:[/bold]")
    for t in d["threads"]:
        vers = f" {t['versions_referenced']}" if t["versions_referenced"] else ""
        console.print(f"  • {t['subject']} ({t['date_range']}){vers}")
        console.print(f"    [blue]{t['archive_url']}[/blue]")


@app.command("search")
def search_cmd(query: str, limit: int = typer.Option(25)) -> None:
    """Full-text search over thread subjects and summaries."""
    with session_scope() as s:
        rows = queries.search_threads_fts(s, query, limit=limit)
    for r in rows:
        console.print(f"[bold]{r['subject']}[/bold] ({r['working_group']})")
        console.print(f"  {r['summary_brief']}")
        console.print(f"  [blue]{r['archive_url']}[/blue]\n")


# --------------------------------------------------------------------------- #
# Pipeline + admin commands
# --------------------------------------------------------------------------- #


@app.command("seed-topics")
def seed_topics_cmd() -> None:
    """Load the configured topic taxonomy into the database."""
    with session_scope() as s:
        n = seed_topics(s)
    console.print(f"[green]Seeded {n} topics[/green]")


@app.command("ingest")
def ingest_cmd(
    working_group: str = typer.Option(None, "--working-group", "--wg"),
    since: str = typer.Option(None, help="ISO date; only fetch messages after this"),
    skip_llm: bool = typer.Option(False, help="Ingest + draft sync only, no LLM stages"),
    force: bool = typer.Option(False, help="Override the budget guard"),
) -> None:
    """Run the full ingestion + processing pipeline."""
    wgs = [working_group] if working_group else None
    with session_scope() as s:
        report = run_full_pipeline(
            s, working_groups=wgs, since_iso=since, force=force, skip_llm=skip_llm
        )
    console.print_json(data=report)


@app.command("recategorize")
def recategorize_cmd(force: bool = typer.Option(False)) -> None:
    """Re-categorize all summarized threads against the current taxonomy (cheap)."""
    with session_scope() as s:
        report = recategorize_all(s, force=force)
    console.print_json(data=report)


@app.command("costs")
def costs_cmd() -> None:
    """Show total LLM spend, broken down by pipeline stage."""
    with session_scope() as s:
        total = total_spend(s)
        by_stage = spend_by_stage(s)
    table = Table(title="LLM spend by stage")
    for col in ("stage", "cost_usd", "input_tokens", "output_tokens", "calls"):
        table.add_column(col, justify="right" if col != "stage" else "left")
    for r in by_stage:
        table.add_row(
            r["stage"], f"${r['cost_usd']:.4f}", str(r["input_tokens"]),
            str(r["output_tokens"]), str(r["calls"]),
        )
    console.print(table)
    budget = get_settings().processing.budget_usd
    console.print(f"[bold]Total: ${total:.4f}[/bold] / budget ${budget:.2f}")


if __name__ == "__main__":
    app()
