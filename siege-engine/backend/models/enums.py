"""Shared enumerations used across all models."""

import enum


class ArtifactStatus(str, enum.Enum):
    PENDING = "pending"
    GENERATING = "generating"
    AI_REVIEWING = "ai_reviewing"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


class ArtifactType(str, enum.Enum):
    PROJECT_DOC = "project_doc"
    FEATURE_EXPANSION = "feature_expansion"
    SYSTEM_REQUIREMENTS = "system_requirements"
    SYSTEM_ARCHITECTURE = "system_architecture"
    HIGH_LEVEL_PLAN = "high_level_plan"
    COMPONENT_MAP = "component_map"
    COMPONENT_REQUIREMENTS = "component_requirements"
    COMPONENT_ARCHITECTURE = "component_architecture"
    COMPONENT_PLAN = "component_plan"
    SUB_COMPONENT_MAP = "sub_component_map"
    SUB_COMPONENT_REQUIREMENTS = "sub_component_requirements"
    SUB_COMPONENT_ARCHITECTURE = "sub_component_architecture"
    SUB_COMPONENT_PLAN = "sub_component_plan"
    CODE = "code"
    CODE_REVIEW = "code_review"


class ExecutionMode(str, enum.Enum):
    GATED = "gated"
    ASYNC = "async"


class StageStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    AI_REVIEW = "ai_review"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SKIPPED = "skipped"
    FAILED = "failed"


class FanOutStrategy(str, enum.Enum):
    NONE = "none"
    COMPONENT = "component"
    SUB_COMPONENT = "sub_component"
    LEAF = "leaf"


class StopPoint(str, enum.Enum):
    END_OF_PHASE = "end_of_phase"
    BEFORE_CODE = "before_code"
    EVERY_ARTIFACT = "every_artifact"
    # Legacy values kept for migration compatibility
    AFTER_ALL = "after_all"
    AT_FAN_OUT = "at_fan_out"
    AFTER_TRIPLETS = "after_triplets"


class PipelineRunStatus(str, enum.Enum):
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
