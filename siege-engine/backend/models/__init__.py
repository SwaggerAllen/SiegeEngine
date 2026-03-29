"""Domain-split models package. Re-exports everything for backward compatibility."""

from backend.database import Base
from backend.models.chat import ChatMessage
from backend.models.artifact import (
    Artifact,
    ArtifactComment,
    ArtifactDependency,
    ComponentDefinition,
)
from backend.models.auth import GitHubCredential, InviteLink, User
from backend.models.enums import (
    ArtifactStatus,
    ArtifactType,
    ExecutionMode,
    FanOutStrategy,
    PipelineRunStatus,
    StageStatus,
    StopPoint,
)
from backend.models.input_document import InputDocument
from backend.models.job import Job
from backend.models.pipeline import (
    PipelineConfig,
    PipelineRun,
    PromptConfig,
    StageDefinition,
    StageExecution,
)
from backend.models.pipeline_events import PipelineEvent, PipelineSnapshot
from backend.models.project import Project

__all__ = [
    "Base",
    # Chat
    "ChatMessage",
    # Enums
    "ArtifactStatus",
    "ArtifactType",
    "ExecutionMode",
    "FanOutStrategy",
    "PipelineRunStatus",
    "StageStatus",
    "StopPoint",
    # Auth
    "GitHubCredential",
    "InviteLink",
    "User",
    # Project
    "Project",
    # Artifact
    "Artifact",
    "ArtifactComment",
    "ArtifactDependency",
    "ComponentDefinition",
    # Input Documents
    "InputDocument",
    # Job
    "Job",
    # Pipeline
    "PipelineConfig",
    "PipelineRun",
    "PromptConfig",
    "StageDefinition",
    "StageExecution",
    # Event sourcing
    "PipelineEvent",
    "PipelineSnapshot",
]
