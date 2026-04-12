"""Instruction vocabulary — the bulleted-prose operations the LLM regen
layer eventually consumes.

Instructions describe *intended* changes to the structured model. They
are not events: an instruction is what the user (or a UI action) asks
for, and the regen pipeline executes one by appending the resulting
events. In this phase, instructions are only rendered and enqueued —
execution is stubbed.

Each model carries entity IDs *and* human-readable names so the
rendered form reads naturally to the LLM.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class _InstructionBase(BaseModel):
    """Shared config: strict, extra-forbidden, frozen."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    def render(self) -> str:
        """Render the instruction to a single bulleted line."""
        raise NotImplementedError


# ── Create / Delete / Rename ─────────────────────────────────────────


class Create(_InstructionBase):
    instruction_type: Literal["Create"] = "Create"
    node_id: str
    tier: Literal["feat", "resp", "comp", "impl"]
    name: str
    parent_id: str | None = None
    parent_name: str | None = None

    def render(self) -> str:
        parent = (
            f' under {self.parent_name or self.parent_id}'
            if self.parent_id
            else ""
        )
        return f'- Create {self.tier} "{self.name}" ({self.node_id}){parent}'


class Delete(_InstructionBase):
    instruction_type: Literal["Delete"] = "Delete"
    node_id: str
    name: str

    def render(self) -> str:
        return f'- Delete "{self.name}" ({self.node_id})'


class Rename(_InstructionBase):
    instruction_type: Literal["Rename"] = "Rename"
    node_id: str
    old_name: str
    new_name: str

    def render(self) -> str:
        return (
            f'- Rename {self.node_id} from "{self.old_name}" to '
            f'"{self.new_name}" (preserve existing content)'
        )


# ── Mapping / Parentage ──────────────────────────────────────────────


class ReassignMapping(_InstructionBase):
    """Re-parent a node (e.g. move a responsibility to a different feature)."""

    instruction_type: Literal["ReassignMapping"] = "ReassignMapping"
    node_id: str
    name: str
    new_parent_id: str | None
    new_parent_name: str | None

    def render(self) -> str:
        if self.new_parent_id is None:
            return f'- Detach "{self.name}" ({self.node_id}) from its current parent'
        return (
            f'- Reassign "{self.name}" ({self.node_id}) under '
            f'{self.new_parent_name or self.new_parent_id}'
        )


# ── Promotion / Demotion ─────────────────────────────────────────────


class Promote(_InstructionBase):
    instruction_type: Literal["Promote"] = "Promote"
    node_id: str
    name: str
    new_tier: Literal["feat", "resp", "comp", "impl"]

    def render(self) -> str:
        return f'- Promote "{self.name}" ({self.node_id}) to {self.new_tier}'


class Demote(_InstructionBase):
    instruction_type: Literal["Demote"] = "Demote"
    node_id: str
    name: str
    new_tier: Literal["feat", "resp", "comp", "impl"]
    new_parent_id: str | None = None
    new_parent_name: str | None = None

    def render(self) -> str:
        parent = (
            f' under {self.new_parent_name or self.new_parent_id}'
            if self.new_parent_id
            else ""
        )
        return f'- Demote "{self.name}" ({self.node_id}) to {self.new_tier}{parent}'


# ── Merge / Split ────────────────────────────────────────────────────


class Merge(_InstructionBase):
    instruction_type: Literal["Merge"] = "Merge"
    source_ids: list[str] = Field(..., min_length=2)
    source_names: list[str] = Field(..., min_length=2)
    dest_id: str
    dest_name: str

    def render(self) -> str:
        names = " and ".join(f'"{n}"' for n in self.source_names)
        ids = ", ".join(self.source_ids)
        return (
            f'- Merge {names} ({ids}) into a single entity named '
            f'"{self.dest_name}" ({self.dest_id})'
        )


class Split(_InstructionBase):
    instruction_type: Literal["Split"] = "Split"
    source_id: str
    source_name: str
    dest_ids: list[str] = Field(..., min_length=2)
    dest_names: list[str] = Field(..., min_length=2)

    def render(self) -> str:
        parts = ", ".join(
            f'"{n}" ({i})' for n, i in zip(self.dest_names, self.dest_ids, strict=True)
        )
        return f'- Split "{self.source_name}" ({self.source_id}) into {parts}'


# ── Edges ────────────────────────────────────────────────────────────


class AddDependency(_InstructionBase):
    instruction_type: Literal["AddDependency"] = "AddDependency"
    source_id: str
    source_name: str
    target_id: str
    target_name: str

    def render(self) -> str:
        return (
            f'- Add dependency: "{self.source_name}" ({self.source_id}) '
            f'depends on "{self.target_name}" ({self.target_id})'
        )


class RemoveDependency(_InstructionBase):
    instruction_type: Literal["RemoveDependency"] = "RemoveDependency"
    source_id: str
    source_name: str
    target_id: str
    target_name: str

    def render(self) -> str:
        return (
            f'- Remove dependency: "{self.source_name}" ({self.source_id}) '
            f'no longer depends on "{self.target_name}" ({self.target_id})'
        )


class AddDomainParent(_InstructionBase):
    instruction_type: Literal["AddDomainParent"] = "AddDomainParent"
    source_id: str
    source_name: str
    target_id: str
    target_name: str

    def render(self) -> str:
        return (
            f'- Set domain parent: presentational "{self.source_name}" '
            f'({self.source_id}) maps to domain "{self.target_name}" '
            f'({self.target_id})'
        )


class RemoveDomainParent(_InstructionBase):
    instruction_type: Literal["RemoveDomainParent"] = "RemoveDomainParent"
    source_id: str
    source_name: str
    target_id: str
    target_name: str

    def render(self) -> str:
        return (
            f'- Remove domain parent: presentational "{self.source_name}" '
            f'({self.source_id}) unmapped from "{self.target_name}" '
            f'({self.target_id})'
        )


# ── Discriminated union + registry ───────────────────────────────────

Instruction = Annotated[
    Union[
        Create,
        Delete,
        Rename,
        ReassignMapping,
        Promote,
        Demote,
        Merge,
        Split,
        AddDependency,
        RemoveDependency,
        AddDomainParent,
        RemoveDomainParent,
    ],
    Field(discriminator="instruction_type"),
]


_INSTRUCTION_TYPES: dict[str, type[_InstructionBase]] = {
    "Create": Create,
    "Delete": Delete,
    "Rename": Rename,
    "ReassignMapping": ReassignMapping,
    "Promote": Promote,
    "Demote": Demote,
    "Merge": Merge,
    "Split": Split,
    "AddDependency": AddDependency,
    "RemoveDependency": RemoveDependency,
    "AddDomainParent": AddDomainParent,
    "RemoveDomainParent": RemoveDomainParent,
}


def instruction_from_row(instruction_type: str, payload: dict) -> _InstructionBase:
    """Rehydrate an instruction from a ``pending_instructions`` row."""
    cls = _INSTRUCTION_TYPES[instruction_type]
    return cls.model_validate(payload)
