"""End-to-end pipeline test with fake LLM + datatracker (no network, no API key)."""
from __future__ import annotations

import json

from wgtracker import queries
from wgtracker.llm.batch import BatchRequest, BatchResult
from wgtracker.models import Message
from wgtracker.pipeline import (
    ingest_working_group,
    run_categorization,
    run_prefilter,
    run_summarization,
    seed_topics,
    sync_drafts,
)
from wgtracker.processing.drafts import DraftMetadata

MBOX = b"""From alice@example.com Mon Jan 01 00:00:00 2025
Message-ID: <m1@example.com>
From: Alice Example <alice@example.com>
Subject: Federation across instances
Date: Mon, 06 Jan 2025 10:00:00 +0000
Archived-At: <https://mailarchive.ietf.org/arch/msg/mls/aaa/>

I think draft-ietf-mls-extensions-04 should address cross-instance federation.

From bob@example.org Mon Jan 01 00:00:00 2025
Message-ID: <m2@example.org>
In-Reply-To: <m1@example.com>
References: <m1@example.com>
From: Bob <bob@example.org>
Subject: Re: Federation across instances
Date: Tue, 07 Jan 2025 12:00:00 +0000
Archived-At: <https://mailarchive.ietf.org/arch/msg/mls/bbb/>

> I think draft-ietf-mls-extensions-04 should address cross-instance federation.
Agreed, the federation story needs cross-server interop.
"""


class FakeRunner:
    """Stand-in BatchRunner. Routes each request to a canned response by prefix."""

    def __init__(self, responder):
        self.responder = responder
        self._reqs: dict[str, BatchRequest] = {}

    def submit(self, requests: list[BatchRequest]) -> str:
        self._reqs = {r.custom_id: r for r in requests}
        return "fake-batch"

    def wait_and_collect(self, batch_id: str) -> dict[str, BatchResult]:
        out = {}
        for cid, req in self._reqs.items():
            text = self.responder(cid, req)
            out[cid] = BatchResult(
                custom_id=cid, succeeded=True, text=text, input_tokens=100, output_tokens=50
            )
        return out


class FakeDatatracker:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def fetch_draft(self, name):
        return DraftMetadata(
            draft_name=name,
            title="MLS Extensions",
            current_version="-04",
            working_group="mls",
            status="Active Internet-Draft",
            abstract="Defines extensions for MLS.",
            datatracker_url=f"https://datatracker.ietf.org/doc/{name}/",
        )


def _responder(cid: str, req: BatchRequest) -> str:
    if cid.startswith("prefilter::"):
        return json.dumps({"admin": False})
    if cid.startswith("summarize::"):
        return json.dumps(
            {
                "summary": "Alice proposed that draft-ietf-mls-extensions-04 address "
                "cross-instance federation; Bob agreed on the need for cross-server interop.",
                "key_positions": [
                    {"position": "extensions should cover federation", "holder": "Alice", "context": "interop"}
                ],
                "consensus_state": "emerging_consensus",
                "status": "active",
            }
        )
    if cid.startswith("categorize::"):
        return json.dumps([{"topic": "federation", "confidence": 0.9}])
    return "{}"


def test_full_pipeline_with_fakes(session):
    seed_topics(session)

    # Stage 1
    res = ingest_working_group(session, "mls", raw_mbox=MBOX)
    assert res["ingested"] == 2
    assert res["threads"] == 1
    assert session.query(Message).count() == 2

    # Idempotency: re-ingesting the same mbox adds nothing.
    res2 = ingest_working_group(session, "mls", raw_mbox=MBOX)
    assert res2["ingested"] == 0
    assert session.query(Message).count() == 2

    # Stage 3: drafts
    dres = sync_drafts(session, working_group="mls", client=FakeDatatracker())
    assert dres["drafts"] == 1
    assert dres["links"] == 1

    runner = FakeRunner(_responder)
    # Stage 2 (LLM): prefilter
    pf = run_prefilter(session, runner=runner)
    assert pf["classified"] == 2

    # Stage 4: summarization
    sm = run_summarization(session, runner=runner)
    assert sm["summarized"] == 1

    # Idempotency: nothing changed -> no re-summary.
    assert run_summarization(session, runner=runner)["summarized"] == 0

    # Stage 5: categorization
    cat = run_categorization(session, runner=runner)
    assert cat["categorized"] == 1

    # Queries
    rows = queries.list_threads(session, topic="federation", working_group="mls")
    assert len(rows) == 1
    tid = rows[0]["thread_id"]
    detail = queries.get_thread_detail(session, tid)
    assert detail["consensus_state"] == "emerging_consensus"
    assert detail["archive_url"] == "https://mailarchive.ietf.org/arch/msg/mls/aaa/"
    assert any(d["draft_name"] == "draft-ietf-mls-extensions" for d in detail["referenced_drafts"])
    assert detail["referenced_drafts"][0]["versions_referenced"] == ["-04"]

    drafts = queries.list_drafts(session, topic="federation")
    assert drafts[0]["draft_name"] == "draft-ietf-mls-extensions"
    assert drafts[0]["thread_count"] == 1

    parts = queries.participants(session, topic="federation")
    assert {p["from_address"] for p in parts} == {"alice@example.com", "bob@example.org"}

    overview = queries.topic_overview(session, topic="federation")
    assert overview["thread_count"] == 1


def test_fts_search(session):
    seed_topics(session)
    ingest_working_group(session, "mls", raw_mbox=MBOX)
    runner = FakeRunner(_responder)
    run_prefilter(session, runner=runner)
    run_summarization(session, runner=runner)
    hits = queries.search_threads_fts(session, "federation interop")
    assert len(hits) == 1
