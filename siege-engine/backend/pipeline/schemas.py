from pydantic import BaseModel


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
