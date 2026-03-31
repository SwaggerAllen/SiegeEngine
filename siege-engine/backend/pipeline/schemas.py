from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

# ──── Legacy request schemas (kept for internal use) ────


class PipelineStartRequest(BaseModel):
    ai_loops: int = 1  # Number of AI self-improvement loops (generate→review cycles)
    stop_point: str = "end_of_phase"  # "end_of_phase", "before_code", "every_artifact"
    start_stage_key: str | None = None  # Stage to start from (None = first incomplete)
    start_component_key: str | None = None  # Component to scope the run to


class ResumeRequest(BaseModel):
    execution_id: str
    action: str  # "approved", "rejected", or "save_feedback"
    notes: str | None = None
    edited_content: str | None = None


class ReviseRequest(BaseModel):
    artifact_id: str
    feedback: str


class ResolveStaleRequest(BaseModel):
    artifact_id: str
    action: str  # "approved", "rejected", or "save_feedback"
    notes: str | None = None
    edited_content: str | None = None


class RegenDownstreamRequest(BaseModel):
    artifact_id: str


class ResumeRunRequest(BaseModel):
    ai_loops: int = 1
    stop_point: str = "end_of_phase"
    start_stage_key: str | None = None
    start_component_key: str | None = None


class CancelRequest(BaseModel):
    open_pr: bool = False
    pr_title: str | None = None
    pr_body: str | None = None
    base_branch: str = "main"


class RegenerateRequest(BaseModel):
    artifact_ids: list[str]


class PromptPreviewRequest(BaseModel):
    artifact_id: str
    human_notes: str | None = None  # Optional draft feedback for "what-if" preview


class TriggerStageRequest(BaseModel):
    stage_key: str
    component_key: str | None = None


# ──── Discriminated union: POST /action ────


class StartAction(BaseModel):
    type: Literal["start"] = "start"
    ai_loops: int = 1
    stop_point: str = "end_of_phase"
    start_stage_key: str | None = None
    start_component_key: str | None = None


class ResumeRunAction(BaseModel):
    type: Literal["resume_run"] = "resume_run"
    ai_loops: int = 1
    stop_point: str = "end_of_phase"
    start_stage_key: str | None = None
    start_component_key: str | None = None


class PropagateAction(BaseModel):
    type: Literal["propagate"] = "propagate"


class CancelAction(BaseModel):
    type: Literal["cancel"] = "cancel"
    open_pr: bool = False
    pr_title: str | None = None
    pr_body: str | None = None
    base_branch: str = "main"


class ResetAllAction(BaseModel):
    type: Literal["reset_all"] = "reset_all"


class ResumeStageAction(BaseModel):
    type: Literal["resume_stage"] = "resume_stage"
    execution_id: str
    action: str  # "approved", "rejected", or "save_feedback"
    notes: str | None = None
    edited_content: str | None = None


class ReviseAction(BaseModel):
    type: Literal["revise"] = "revise"
    artifact_id: str
    feedback: str


class ResolveStaleAction(BaseModel):
    type: Literal["resolve_stale"] = "resolve_stale"
    artifact_id: str
    action: str  # "approved", "rejected", or "save_feedback"
    notes: str | None = None
    edited_content: str | None = None


class RegenDownstreamAction(BaseModel):
    type: Literal["regen_downstream"] = "regen_downstream"
    artifact_id: str


class CancelStageAction(BaseModel):
    type: Literal["cancel_stage"] = "cancel_stage"
    execution_id: str


class ForceRestartAction(BaseModel):
    type: Literal["force_restart"] = "force_restart"
    execution_id: str


class TriggerStageAction(BaseModel):
    type: Literal["trigger_stage"] = "trigger_stage"
    stage_key: str
    component_key: str | None = None


class RetryAction(BaseModel):
    type: Literal["retry"] = "retry"
    execution_id: str


class PruneAction(BaseModel):
    type: Literal["prune"] = "prune"
    artifact_id: str


class ReparseAction(BaseModel):
    type: Literal["reparse"] = "reparse"
    artifact_id: str


class RegenerateAction(BaseModel):
    type: Literal["regenerate"] = "regenerate"
    artifact_ids: list[str]


class PromptPreviewAction(BaseModel):
    type: Literal["prompt_preview"] = "prompt_preview"
    artifact_id: str
    human_notes: str | None = None


class RetrySummaryAction(BaseModel):
    type: Literal["retry_summary"] = "retry_summary"
    artifact_id: str


class ReconcileAction(BaseModel):
    type: Literal["reconcile"] = "reconcile"


class ReconstructAction(BaseModel):
    type: Literal["reconstruct"] = "reconstruct"


class RevertAction(BaseModel):
    type: Literal["revert"] = "revert"
    sequence: int


class CheckBlockingPRAction(BaseModel):
    type: Literal["check_blocking_pr"] = "check_blocking_pr"


class DismissBlockingPRAction(BaseModel):
    type: Literal["dismiss_blocking_pr"] = "dismiss_blocking_pr"


PipelineAction = Annotated[
    Union[
        StartAction,
        ResumeRunAction,
        PropagateAction,
        CancelAction,
        ResetAllAction,
        ResumeStageAction,
        ReviseAction,
        ResolveStaleAction,
        RegenDownstreamAction,
        CancelStageAction,
        ForceRestartAction,
        TriggerStageAction,
        RetryAction,
        PruneAction,
        ReparseAction,
        RegenerateAction,
        PromptPreviewAction,
        RetrySummaryAction,
        ReconcileAction,
        ReconstructAction,
        RevertAction,
        CheckBlockingPRAction,
        DismissBlockingPRAction,
    ],
    Field(discriminator="type"),
]


class StageDefinitionResponse(BaseModel):
    id: str
    stage_key: str
    display_name: str
    order_index: int
    output_artifact_type: str
    input_stage_keys: list[str]
    fan_out_strategy: str
    ai_review_enabled: bool
    human_review_enabled: bool
    prompt_template_key: str
    model_override: str | None
    temperature_override: float | None

    model_config = {"from_attributes": True}


class StageDefinitionUpdate(BaseModel):
    display_name: str | None = None
    model_override: str | None = None
    temperature_override: float | None = None
    ai_review_enabled: bool | None = None
    human_review_enabled: bool | None = None


class PipelineConfigResponse(BaseModel):
    id: str
    execution_mode: str
    default_model: str
    default_temperature: float
    stages: list[StageDefinitionResponse]

    model_config = {"from_attributes": True}


class PipelineConfigUpdate(BaseModel):
    execution_mode: str | None = None
    default_model: str | None = None
    default_temperature: float | None = None


class PromptConfigResponse(BaseModel):
    id: str
    stage_definition_id: str
    system_message: str
    output_format_instructions: str
    context_template: str
    revision_instructions: str
    model: str | None
    temperature: float | None
    max_tokens: int

    model_config = {"from_attributes": True}


class PromptConfigUpdate(BaseModel):
    system_message: str | None = None
    output_format_instructions: str | None = None
    context_template: str | None = None
    revision_instructions: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


class StageExecutionResponse(BaseModel):
    id: str
    stage_key: str
    component_key: str | None
    status: str
    artifact_id: str | None
    started_at: str | None
    completed_at: str | None
    error_message: str | None
    run_id: str

    model_config = {"from_attributes": True}


class PipelineRunResponse(BaseModel):
    id: str
    run_number: int
    run_id: str
    status: str
    ai_loops: int
    stop_point: str
    start_stage_key: str | None
    start_component_key: str | None
    git_commit_sha: str | None
    started_at: str | None
    completed_at: str | None

    model_config = {"from_attributes": True}
