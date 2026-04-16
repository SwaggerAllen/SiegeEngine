"""Tests for ``validate_reference`` + ``parse_and_validate_reference``.

Enforces the Phase 6.6 ``<reference>`` grammar:

- required ``<title>`` (non-empty plain text)
- required ``<body>`` (non-empty, opaque markdown)
- optional ``<see-also>`` with ``<ref to="ref_..."/>`` children
- children in fixed order: title → body → see-also
"""

from __future__ import annotations

import pytest

from backend.graph.parsers.validators import (
    ReferenceEntry,
    ReferenceRef,
    ValidationError,
    parse_and_validate_reference,
    validate_reference,
)
from backend.graph.parsers.xml_sections import ParseError, extract_tag_tree


def _parse(raw: str):
    return extract_tag_tree(raw, "reference")


class TestValidReference:
    def test_minimal_title_body(self):
        raw = "<reference><title>Runbook</title><body>Deploy steps.</body></reference>"
        entry = validate_reference(_parse(raw), raw_content=raw)
        assert isinstance(entry, ReferenceEntry)
        assert entry.title == "Runbook"
        assert entry.body == "Deploy steps."
        assert entry.see_also_refs == ()
        assert entry.raw_content == raw

    def test_with_see_also(self):
        raw = (
            "<reference>"
            "<title>Runbook</title>"
            "<body>Deploy steps.</body>"
            '<see-also><ref to="ref_ABCDEFGH"/></see-also>'
            "</reference>"
        )
        entry = validate_reference(_parse(raw), raw_content=raw)
        assert entry.see_also_refs == (ReferenceRef(to="ref_ABCDEFGH"),)

    def test_multiple_see_also_refs(self):
        raw = (
            "<reference>"
            "<title>Runbook</title>"
            "<body>Body text.</body>"
            "<see-also>"
            '<ref to="ref_ABCDEFGH"/>'
            '<ref to="ref_JKMNPQRS"/>'
            "</see-also>"
            "</reference>"
        )
        entry = validate_reference(_parse(raw), raw_content=raw)
        assert len(entry.see_also_refs) == 2

    def test_body_with_markdown_content_preserved(self):
        raw = (
            "<reference>"
            "<title>DSL Spec</title>"
            "<body>## Header\n\n- one\n- two\n\nPara.</body>"
            "</reference>"
        )
        entry = validate_reference(_parse(raw), raw_content=raw)
        assert "Header" in entry.body

    def test_parse_and_validate_reference_end_to_end(self):
        raw = "<reference><title>X</title><body>Y.</body></reference>"
        entry = parse_and_validate_reference(raw)
        assert entry.title == "X"


class TestStructuralErrors:
    def test_wrong_root_tag_rejected(self):
        raw = "<references><title>X</title><body>Y</body></references>"
        with pytest.raises(ParseError):
            # The parse helper only finds <reference>, not <references>
            parse_and_validate_reference(raw)

    def test_root_tag_name_mismatch_via_validate(self):
        # Manually craft a TagNode with the wrong tag
        tree = extract_tag_tree("<other><title>X</title><body>Y</body></other>", "other")
        with pytest.raises(ValidationError, match="Expected root tag <reference>"):
            validate_reference(tree, raw_content="<other/>")

    def test_missing_title_rejected(self):
        raw = "<reference><body>Just body.</body></reference>"
        with pytest.raises(ValidationError, match="missing the required <title>"):
            validate_reference(_parse(raw), raw_content=raw)

    def test_missing_body_rejected(self):
        raw = "<reference><title>Only title.</title></reference>"
        with pytest.raises(ValidationError, match="missing the required <body>"):
            validate_reference(_parse(raw), raw_content=raw)

    def test_empty_title_rejected(self):
        raw = "<reference><title>   </title><body>text</body></reference>"
        with pytest.raises(ValidationError, match="<title> is empty"):
            validate_reference(_parse(raw), raw_content=raw)

    def test_empty_body_rejected(self):
        raw = "<reference><title>Title</title><body>   </body></reference>"
        with pytest.raises(ValidationError, match="<body> is empty"):
            validate_reference(_parse(raw), raw_content=raw)

    def test_unknown_child_rejected(self):
        raw = "<reference><title>X</title><body>Y</body><unexpected>Z</unexpected></reference>"
        with pytest.raises(ValidationError, match="unexpected child <unexpected>"):
            validate_reference(_parse(raw), raw_content=raw)

    def test_duplicate_title_rejected(self):
        raw = "<reference><title>First</title><title>Second</title><body>Y</body></reference>"
        with pytest.raises(ValidationError, match="more than one <title>"):
            validate_reference(_parse(raw), raw_content=raw)

    def test_out_of_order_rejected(self):
        raw = "<reference><body>Y</body><title>X</title></reference>"
        with pytest.raises(ValidationError, match="not in the required order"):
            validate_reference(_parse(raw), raw_content=raw)


class TestSeeAlsoValidation:
    def test_see_also_with_name_form_rejected(self):
        raw = (
            "<reference>"
            "<title>X</title>"
            "<body>Y</body>"
            '<see-also><ref name="something"/></see-also>'
            "</reference>"
        )
        with pytest.raises(ValidationError, match="uses name= form"):
            validate_reference(_parse(raw), raw_content=raw)

    def test_see_also_without_to_rejected(self):
        raw = "<reference><title>X</title><body>Y</body><see-also><ref/></see-also></reference>"
        with pytest.raises(ValidationError, match="missing the to attribute"):
            validate_reference(_parse(raw), raw_content=raw)

    def test_see_also_malformed_ref_id_rejected(self):
        raw = (
            "<reference>"
            "<title>X</title>"
            "<body>Y</body>"
            '<see-also><ref to="not_a_ref_id"/></see-also>'
            "</reference>"
        )
        with pytest.raises(ValidationError, match="not a valid ref ID"):
            validate_reference(_parse(raw), raw_content=raw)

    def test_see_also_duplicate_rejected(self):
        raw = (
            "<reference>"
            "<title>X</title>"
            "<body>Y</body>"
            "<see-also>"
            '<ref to="ref_ABCDEFGH"/>'
            '<ref to="ref_ABCDEFGH"/>'
            "</see-also>"
            "</reference>"
        )
        with pytest.raises(ValidationError, match="duplicate reference"):
            validate_reference(_parse(raw), raw_content=raw)

    def test_see_also_with_non_ref_child_rejected(self):
        raw = (
            "<reference><title>X</title><body>Y</body><see-also><whatever/></see-also></reference>"
        )
        with pytest.raises(ValidationError, match="unexpected child <whatever>"):
            validate_reference(_parse(raw), raw_content=raw)
