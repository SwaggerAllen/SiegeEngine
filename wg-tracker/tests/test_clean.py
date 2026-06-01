from wgtracker.processing.clean import clean_body, strip_quotes, strip_signature


def test_strip_quotes_removes_quoted_lines_and_attribution():
    text = (
        "Here is my reply.\n"
        "On Mon, Jan 6, 2025, Alice wrote:\n"
        "> original line one\n"
        "> original line two\n"
        "More of my reply."
    )
    out = strip_quotes(text)
    assert "original line" not in out
    assert "Alice wrote:" not in out
    assert "Here is my reply." in out
    assert "More of my reply." in out


def test_strip_signature_at_rfc_delimiter():
    text = "Real content here.\n--\nAlice\nPGP: 0xABC"
    out = strip_signature(text)
    assert out == "Real content here."


def test_clean_body_full_pipeline():
    text = (
        "My actual point about the draft.\n\n\n"
        "> quoted nonsense\n"
        "-- \n"
        "Sent from my phone"
    )
    out = clean_body(text)
    assert "quoted nonsense" not in out
    assert "Sent from my phone" not in out
    assert "My actual point about the draft." in out


def test_clean_empty():
    assert clean_body("") == ""
