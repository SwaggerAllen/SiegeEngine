"""Thread reconstruction from individual messages.

Primary signal: References / In-Reply-To headers (union-find over message IDs).
Fallback for broken chains: normalized-subject + time-proximity grouping, so a
message whose In-Reply-To points at something we never ingested still lands in a
sensible thread instead of becoming an orphan.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import timedelta

from .mail_parser import ParsedMessage

_RE_PREFIX = re.compile(r"^\s*(re|aw|fwd|fw|sv|antw)\s*(\[\d+\])?\s*:\s*", re.IGNORECASE)
_WS = re.compile(r"\s+")

# Messages with no header linkage are grouped if subjects match and they fall
# within this window of an existing thread message.
_SUBJECT_PROXIMITY = timedelta(days=30)


def normalize_subject(subject: str | None) -> str:
    if not subject:
        return ""
    s = subject
    # Strip any stacked Re:/Fwd: prefixes.
    while True:
        new = _RE_PREFIX.sub("", s)
        if new == s:
            break
        s = new
    s = _WS.sub(" ", s).strip().lower()
    return s


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        # Path compression.
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


@dataclass
class ReconstructedThread:
    thread_id: str
    working_group: str
    messages: list[ParsedMessage] = field(default_factory=list)

    @property
    def root(self) -> ParsedMessage:
        return min(self.messages, key=lambda m: (m.date is None, m.date))

    @property
    def subject(self) -> str:
        return self.root.subject or "(no subject)"


def _thread_id(working_group: str, anchor: str) -> str:
    digest = hashlib.sha1(f"{working_group}:{anchor}".encode()).hexdigest()[:16]
    return f"{working_group}-{digest}"


def reconstruct(messages: list[ParsedMessage], working_group: str) -> list[ReconstructedThread]:
    """Group parsed messages into threads. Deterministic given the same input set."""
    uf = _UnionFind()

    # 1. Header-based linkage.
    for m in messages:
        uf.find(m.message_id)
        parents = list(m.references) + ([m.in_reply_to] if m.in_reply_to else [])
        for p in parents:
            if p:
                uf.union(m.message_id, p)

    # 2. Subject + time-proximity fallback for messages whose linkage is broken
    #    (parents reference IDs we never ingested). We group same-normalized-subject
    #    messages that are close in time.
    subject_groups: dict[str, list[ParsedMessage]] = {}
    for m in messages:
        subject_groups.setdefault(normalize_subject(m.subject), []).append(m)
    for norm, group in subject_groups.items():
        if not norm or len(group) < 2:
            continue
        group_sorted = sorted(group, key=lambda x: (x.date is None, x.date))
        for prev, cur in zip(group_sorted, group_sorted[1:], strict=False):
            if prev.date and cur.date and (cur.date - prev.date) <= _SUBJECT_PROXIMITY:
                uf.union(prev.message_id, cur.message_id)
            elif not prev.date or not cur.date:
                uf.union(prev.message_id, cur.message_id)

    # 3. Collect groups by representative root.
    groups: dict[str, list[ParsedMessage]] = {}
    for m in messages:
        root = uf.find(m.message_id)
        groups.setdefault(root, []).append(m)

    threads: list[ReconstructedThread] = []
    for members in groups.values():
        # Anchor the thread_id on the earliest *known* message's ID so the id is
        # stable across re-ingestion even as later replies arrive.
        anchor_msg = min(members, key=lambda m: (m.date is None, m.date))
        tid = _thread_id(working_group, anchor_msg.message_id)
        threads.append(
            ReconstructedThread(thread_id=tid, working_group=working_group, messages=members)
        )
    return threads
