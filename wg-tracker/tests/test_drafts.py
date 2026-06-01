from wgtracker.processing.drafts import extract_references


def test_extract_bare_and_versioned():
    text = "See draft-ietf-mls-extensions and also draft-ietf-mls-extensions-04 specifically."
    refs = extract_references(text)
    assert "draft-ietf-mls-extensions" in refs
    assert refs["draft-ietf-mls-extensions"].versions == {"-04"}


def test_extract_rfc():
    refs = extract_references("This is in RFC 9420 and RFC9420 again.")
    assert "rfc9420" in refs


def test_extract_datatracker_and_archive_links():
    text = (
        "https://datatracker.ietf.org/doc/draft-ietf-mimi-protocol/ and "
        "https://www.ietf.org/archive/id/draft-ietf-mls-extensions-03.html"
    )
    refs = extract_references(text)
    assert "draft-ietf-mimi-protocol" in refs
    assert "draft-ietf-mls-extensions" in refs
    assert "-03" in refs["draft-ietf-mls-extensions"].versions


def test_no_references():
    assert extract_references("nothing here") == {}
    assert extract_references("") == {}
