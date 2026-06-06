"""v2 structured model — events, reducer, queue, instructions, queries.

Every write to the structured model goes through
:func:`backend.graph.reducer.append_event`. Every read goes through
:mod:`backend.graph.queries`. Application code does not touch the
projection ORM models directly.

Importing this package also registers the v2 job handlers:
  * ``v2.apply_instructions``
  * ``v2.rename_rewrite``
  * ``v2.expand_single_feature``

Per-tier generation / mint / review handlers retired with the
read-side rewrite; per-tier work happens in Claude Code skills now.
Refs and vocab now move through the v3 git-backed write endpoints
(see ``references_git_routes.py`` and ``vocabulary_git_routes.py``)
plus the ``/create_ref`` / ``/create_vocab`` skills — no job handler.
"""

from backend.graph import queue as _queue
from backend.graph.handlers import expand_single_feature as _expand_single_feature_handler
from backend.graph.handlers import rename_rewrite as _rename_rewrite_handler

_queue.register_apply_handler()
_rename_rewrite_handler.register()
_expand_single_feature_handler.register()
