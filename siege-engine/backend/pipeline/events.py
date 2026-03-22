"""Pipeline event type constants."""

# Run lifecycle
RUN_CREATED = "run_created"
RUN_COMPLETED = "run_completed"

# Stage lifecycle
STAGE_QUEUED = "stage_queued"
STAGE_STARTED = "stage_started"
GENERATION_COMPLETED = "generation_completed"
AI_REVIEW_STARTED = "ai_review_started"
AI_REVIEW_COMPLETED = "ai_review_completed"
AWAITING_HUMAN_REVIEW = "awaiting_human_review"
HUMAN_APPROVED = "human_approved"
HUMAN_REJECTED = "human_rejected"
FEEDBACK_SAVED = "feedback_saved"
STAGE_FAILED = "stage_failed"
STAGE_SKIPPED = "stage_skipped"

# Artifact lifecycle
ARTIFACT_REVISED = "artifact_revised"
STALE_RESOLVED = "stale_resolved"
STALENESS_PROPAGATED = "staleness_propagated"
ARTIFACT_PRUNED = "artifact_pruned"
ARTIFACT_COMMITTED = "artifact_committed"

# Cascade & carry-over
CASCADE_STARTED = "cascade_started"
CASCADE_COMPLETED = "cascade_completed"
CARRIED_OVER = "carried_over"

# Comments & feedback
COMMENT_ADDED = "comment_added"

# Progress
GENERATION_PROGRESS = "generation_progress"

# Pipeline state
PIPELINE_PAUSED = "pipeline_paused"
PIPELINE_RESUMED = "pipeline_resumed"

# Global
PIPELINE_RESET = "pipeline_reset"
STAGE_RETRIED = "stage_retried"

ALL_EVENT_TYPES = frozenset({
    RUN_CREATED, RUN_COMPLETED,
    STAGE_QUEUED, STAGE_STARTED, GENERATION_COMPLETED,
    AI_REVIEW_STARTED, AI_REVIEW_COMPLETED,
    AWAITING_HUMAN_REVIEW, HUMAN_APPROVED, HUMAN_REJECTED, FEEDBACK_SAVED,
    STAGE_FAILED, STAGE_SKIPPED,
    ARTIFACT_REVISED, STALE_RESOLVED, STALENESS_PROPAGATED, ARTIFACT_PRUNED,
    ARTIFACT_COMMITTED,
    CASCADE_STARTED, CASCADE_COMPLETED, CARRIED_OVER,
    COMMENT_ADDED,
    GENERATION_PROGRESS,
    PIPELINE_PAUSED, PIPELINE_RESUMED,
    PIPELINE_RESET, STAGE_RETRIED,
})
