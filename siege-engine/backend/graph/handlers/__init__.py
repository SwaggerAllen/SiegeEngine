"""Pipeline job handlers for the v2 structured model.

Each module defines one handler that consumes a payload from the
generic pipeline job queue (``backend.pipeline.queue``) and produces
events via ``backend.graph.reducer.append_event``. Handlers are
registered at import time via a ``register()`` function called from
``backend.graph.__init__``.
"""
