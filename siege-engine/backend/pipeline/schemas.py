from pydantic import BaseModel


class PipelineStartRequest(BaseModel):
    execution_mode: str | None = None  # "gated" or "async"


class ResumeRequest(BaseModel):
    execution_id: str
    action: str  # "approved" or "rejected"
    notes: str | None = None
    edited_content: str | None = None


class ReviseRequest(BaseModel):
    artifact_id: str
    feedback: str


class RegenerateRequest(BaseModel):
    artifact_ids: list[str]


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

    model_config = {"from_attributes": True}


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
