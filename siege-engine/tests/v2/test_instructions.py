"""Tests for backend.graph.instructions — schema + rendering."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.graph.instructions import (
    AddDependency,
    AddDomainParent,
    AddPolicyApplication,
    Create,
    Delete,
    Demote,
    Merge,
    Promote,
    ReassignMapping,
    RemoveDependency,
    RemoveDomainParent,
    RemovePolicyApplication,
    Rename,
    Split,
    instruction_from_row,
)

# (instruction, expected_render)
_FIXTURES = [
    (
        Create(
            node_id="comp_ABCDEFGH",
            tier="comp",
            name="IdentityService",
            parent_id="resp_AAAAAAAA",
            parent_name="Authenticate",
        ),
        '- Create comp "IdentityService" (comp_ABCDEFGH) under Authenticate',
    ),
    (
        Create(node_id="comp_ABCDEFGH", tier="comp", name="Orphan"),
        '- Create comp "Orphan" (comp_ABCDEFGH)',
    ),
    (
        Delete(node_id="comp_ABCDEFGH", name="Foo"),
        '- Delete "Foo" (comp_ABCDEFGH)',
    ),
    (
        Rename(node_id="comp_ABCDEFGH", old_name="Old", new_name="New"),
        '- Rename comp_ABCDEFGH from "Old" to "New" (preserve existing content)',
    ),
    (
        ReassignMapping(
            node_id="resp_AAAAAAAA",
            name="Auth",
            new_parent_id="feat_BBBBBBBB",
            new_parent_name="Identity",
        ),
        '- Reassign "Auth" (resp_AAAAAAAA) under Identity',
    ),
    (
        Promote(node_id="resp_AAAAAAAA", name="Auth", new_tier="feat"),
        '- Promote "Auth" (resp_AAAAAAAA) to feat',
    ),
    (
        Demote(
            node_id="feat_AAAAAAAA",
            name="Auth",
            new_tier="resp",
            new_parent_id="feat_BBBBBBBB",
            new_parent_name="Identity",
        ),
        '- Demote "Auth" (feat_AAAAAAAA) to resp under Identity',
    ),
    (
        Merge(
            source_ids=["comp_AAAAAAAA", "comp_BBBBBBBB"],
            source_names=["A", "B"],
            dest_id="comp_AAAAAAAA",
            dest_name="Merged",
        ),
        '- Merge "A" and "B" (comp_AAAAAAAA, comp_BBBBBBBB) into a single entity named '
        '"Merged" (comp_AAAAAAAA)',
    ),
    (
        Split(
            source_id="comp_AAAAAAAA",
            source_name="Orig",
            dest_ids=["comp_BBBBBBBB", "comp_CCCCCCCC"],
            dest_names=["B", "C"],
        ),
        '- Split "Orig" (comp_AAAAAAAA) into "B" (comp_BBBBBBBB), "C" (comp_CCCCCCCC)',
    ),
    (
        AddDependency(
            source_id="comp_AAAAAAAA",
            source_name="A",
            target_id="comp_BBBBBBBB",
            target_name="B",
        ),
        '- Add dependency: "A" (comp_AAAAAAAA) depends on "B" (comp_BBBBBBBB)',
    ),
    (
        RemoveDependency(
            source_id="comp_AAAAAAAA",
            source_name="A",
            target_id="comp_BBBBBBBB",
            target_name="B",
        ),
        '- Remove dependency: "A" (comp_AAAAAAAA) no longer depends on "B" (comp_BBBBBBBB)',
    ),
    (
        AddDomainParent(
            source_id="comp_AAAAAAAA",
            source_name="LoginView",
            target_id="comp_BBBBBBBB",
            target_name="Auth",
        ),
        '- Set domain parent: presentational "LoginView" (comp_AAAAAAAA) maps to '
        'domain "Auth" (comp_BBBBBBBB)',
    ),
    (
        RemoveDomainParent(
            source_id="comp_AAAAAAAA",
            source_name="LoginView",
            target_id="comp_BBBBBBBB",
            target_name="Auth",
        ),
        '- Remove domain parent: presentational "LoginView" (comp_AAAAAAAA) '
        'unmapped from "Auth" (comp_BBBBBBBB)',
    ),
    (
        AddPolicyApplication(
            policy_id="policy_AAAAAAAA",
            policy_name="LLM calls emit telemetry",
            component_id="comp_BBBBBBBB",
            component_name="IdentityService",
        ),
        '- Apply policy "LLM calls emit telemetry" (policy_AAAAAAAA) '
        'to component "IdentityService" (comp_BBBBBBBB)',
    ),
    (
        RemovePolicyApplication(
            policy_id="policy_AAAAAAAA",
            policy_name="LLM calls emit telemetry",
            component_id="comp_BBBBBBBB",
            component_name="IdentityService",
        ),
        '- Detach policy "LLM calls emit telemetry" (policy_AAAAAAAA) '
        'from component "IdentityService" (comp_BBBBBBBB)',
    ),
]


_FIXTURE_IDS = [f"{type(i).__name__}_{idx}" for idx, (i, _) in enumerate(_FIXTURES)]


@pytest.mark.parametrize("instruction,expected", _FIXTURES, ids=_FIXTURE_IDS)
def test_render_matches_fixture(instruction, expected):
    assert instruction.render() == expected


class TestRoundtrip:
    @pytest.mark.parametrize("instruction,_expected", _FIXTURES)
    def test_dump_validate(self, instruction, _expected):
        payload = instruction.model_dump(mode="json")
        rehydrated = instruction_from_row(instruction.instruction_type, payload)
        assert rehydrated == instruction


class TestSchemaRejection:
    def test_merge_needs_two_sources(self):
        with pytest.raises(ValidationError):
            Merge(
                source_ids=["only_one"],
                source_names=["A"],
                dest_id="d",
                dest_name="D",
            )

    def test_split_needs_two_dests(self):
        with pytest.raises(ValidationError):
            Split(
                source_id="s",
                source_name="S",
                dest_ids=["only_one"],
                dest_names=["A"],
            )

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            Rename(node_id="n", old_name="a", new_name="b", foo="bar")  # type: ignore[call-arg]

    def test_unknown_instruction_type(self):
        with pytest.raises(KeyError):
            instruction_from_row("NotAnInstruction", {})

    def test_create_rejects_feat_tier(self):
        # ``feat`` was removed from Create.tier — content-less feat
        # nodes are useless to the reqs generator. The v3 substrate's
        # /propose_feature and /add_feature skills handle feat
        # authoring (body in git, intent paragraph included).
        with pytest.raises(ValidationError):
            Create(node_id="feat_AAAAAAAA", tier="feat", name="X")  # type: ignore[arg-type]
