from email import message_from_bytes

from wgtracker.ingestion.archive import _split_mbox, iter_mbox_messages
from wgtracker.ingestion.mail_parser import parse_message

RAW = b"""From alice@example.com Mon Jan 01 00:00:00 2025
Message-ID: <msg-1@example.com>
From: Alice Example <alice@example.com>
To: mls@ietf.org
Subject: =?utf-8?q?Extension_format_concerns?=
Date: Mon, 06 Jan 2025 10:00:00 +0000
Archived-At: <https://mailarchive.ietf.org/arch/msg/mls/abc123/>

I have concerns about draft-ietf-mls-extensions-04.

From the spec it is unclear.

--
Alice
PGP: 0xDEADBEEF

From bob@example.org Mon Jan 01 00:00:00 2025
Message-ID: <msg-2@example.org>
In-Reply-To: <msg-1@example.com>
References: <msg-1@example.com>
From: Bob <bob@example.org>
Subject: Re: Extension format concerns
Date: Tue, 07 Jan 2025 12:00:00 +0000

> I have concerns about draft-ietf-mls-extensions-04.
+1, agreed.
"""


def test_split_mbox_finds_two_messages():
    chunks = _split_mbox(RAW)
    assert len(chunks) == 2


def test_parse_headers_and_archive_url():
    msgs = list(iter_mbox_messages(RAW))
    p1 = parse_message(msgs[0])
    assert p1.message_id == "msg-1@example.com"
    assert p1.from_address == "alice@example.com"
    assert p1.from_name == "Alice Example"
    # RFC 2047 encoded subject is decoded.
    assert p1.subject == "Extension format concerns"
    assert p1.archive_url == "https://mailarchive.ietf.org/arch/msg/mls/abc123/"
    assert p1.date.year == 2025 and p1.date.month == 1


def test_parse_references_and_in_reply_to():
    msgs = list(iter_mbox_messages(RAW))
    p2 = parse_message(msgs[1])
    assert p2.in_reply_to == "msg-1@example.com"
    assert p2.references == ["msg-1@example.com"]


def test_missing_message_id_is_skipped():
    raw = b"From x\nFrom: x@y.com\nSubject: no id\n\nbody"
    msg = message_from_bytes(raw)
    assert parse_message(msg) is None
