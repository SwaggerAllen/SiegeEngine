from datetime import UTC, datetime, timedelta

from wgtracker.ingestion.mail_parser import ParsedMessage
from wgtracker.ingestion.threads import normalize_subject, reconstruct

BASE = datetime(2025, 1, 1, tzinfo=UTC)


def _msg(mid, subject, dt_offset_days, in_reply_to=None, refs=None):
    return ParsedMessage(
        message_id=mid,
        from_address=f"{mid}@x.com",
        from_name=None,
        subject=subject,
        date=BASE + timedelta(days=dt_offset_days),
        archive_url=None,
        in_reply_to=in_reply_to,
        references=refs or [],
    )


def test_normalize_subject_strips_re_prefixes():
    assert normalize_subject("Re: Extensions") == "extensions"
    assert normalize_subject("Re: Re: Extensions") == "extensions"
    assert normalize_subject("Fwd: Hello") == "hello"


def test_header_linkage_groups_thread():
    msgs = [
        _msg("a", "Topic", 0),
        _msg("b", "Re: Topic", 1, in_reply_to="a", refs=["a"]),
        _msg("c", "Re: Topic", 2, in_reply_to="b", refs=["a", "b"]),
    ]
    threads = reconstruct(msgs, "mls")
    assert len(threads) == 1
    assert len(threads[0].messages) == 3


def test_broken_chain_falls_back_to_subject_proximity():
    # b references a message we never ingested, but shares a's subject within window.
    msgs = [
        _msg("a", "Shared subject", 0),
        _msg("b", "Re: Shared subject", 2, in_reply_to="missing", refs=["missing"]),
    ]
    threads = reconstruct(msgs, "mls")
    assert len(threads) == 1


def test_distinct_subjects_stay_separate():
    msgs = [_msg("a", "Topic one", 0), _msg("b", "Topic two", 1)]
    threads = reconstruct(msgs, "mls")
    assert len(threads) == 2


def test_thread_id_is_deterministic():
    msgs = [_msg("a", "Topic", 0), _msg("b", "Re: Topic", 1, in_reply_to="a", refs=["a"])]
    t1 = reconstruct(msgs, "mls")[0].thread_id
    t2 = reconstruct(list(reversed(msgs)), "mls")[0].thread_id
    assert t1 == t2
