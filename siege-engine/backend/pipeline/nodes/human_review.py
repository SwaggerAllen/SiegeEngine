# Human review is handled via the API layer, not as an autonomous node.
# In gated mode, the pipeline pauses (stage status = AWAITING_REVIEW)
# and waits for the user to call POST /api/pipeline/{project_id}/resume.
# This module exists as a placeholder for the node interface.
