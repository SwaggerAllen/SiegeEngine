"""MCP server exposing the query interface as tools for Claude.

Every tool returns source ``archive_url``s alongside summaries so Claude can cite
them. Run locally (stdio) connecting to the remote Postgres:

    python -m wgtracker.mcp_server
"""
from __future__ import annotations

from datetime import UTC, datetime

from dateutil import parser as dateparser
from mcp.server.fastmcp import FastMCP

from . import queries
from .db import session_scope
from .logging_conf import configure_logging

configure_logging()
mcp = FastMCP("wg-tracker")


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = dateparser.parse(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


@mcp.tool()
def search_threads(
    topic: str | None = None,
    working_group: str | None = None,
    since: str | None = None,
    until: str | None = None,
    status: str | None = None,
) -> list[dict]:
    """Search archived working-group threads by topic, WG, date range, and status.

    Returns thread_id, subject, date_range, summary_brief, and the source archive_url
    for each match (always cite the archive_url)."""
    with session_scope() as s:
        return queries.list_threads(
            s,
            topic=topic,
            working_group=working_group,
            since=_date(since),
            until=_date(until),
            status=status,
        )


@mcp.tool()
def get_thread_detail(thread_id: str) -> dict | None:
    """Full summary for a thread: summary, key positions, consensus state,
    participants, referenced drafts, and the source archive_url."""
    with session_scope() as s:
        return queries.get_thread_detail(s, thread_id)


@mcp.tool()
def recent_activity(
    topic: str | None = None, working_group: str | None = None, days: int = 30
) -> list[dict]:
    """Threads with activity in the last N days (default 30), summarized, with
    source archive_urls."""
    with session_scope() as s:
        return queries.recent_activity(s, topic=topic, working_group=working_group, days=days)


@mcp.tool()
def topic_overview(topic: str, working_group: str | None = None) -> dict:
    """Aggregated state of discussion for a topic: active threads, consensus
    breakdown, and open questions."""
    with session_scope() as s:
        return queries.topic_overview(s, topic=topic, working_group=working_group)


@mcp.tool()
def list_drafts(
    topic: str | None = None,
    working_group: str | None = None,
    status: str | None = None,
    referenced_since: str | None = None,
) -> list[dict]:
    """List drafts referenced in discussions, with thread_count and datatracker_url."""
    with session_scope() as s:
        return queries.list_drafts(
            s,
            topic=topic,
            working_group=working_group,
            status=status,
            referenced_since=_date(referenced_since),
        )


@mcp.tool()
def get_draft(draft_name: str) -> dict | None:
    """Draft metadata plus the threads referencing it (with dates, version
    references, summary snippets, and source archive_urls)."""
    with session_scope() as s:
        return queries.get_draft(s, draft_name)


@mcp.tool()
def draft_discussion_history(draft_name: str) -> dict | None:
    """Chronological history of threads about a draft, with which version each
    discussed and the source archive_urls."""
    with session_scope() as s:
        return queries.draft_discussion_history(s, draft_name)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
