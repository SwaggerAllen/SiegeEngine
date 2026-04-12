"""v2 structured model — events, reducer, queue, instructions, queries.

Every write to the structured model goes through
:func:`backend.graph.reducer.append_event`. Every read goes through
:mod:`backend.graph.queries`. Application code does not touch the
projection ORM models directly.

Importing this package also registers the ``v2.apply_instructions``
handler with the job queue.
"""

from backend.graph import queue as _queue

_queue.register_stub_handler()
