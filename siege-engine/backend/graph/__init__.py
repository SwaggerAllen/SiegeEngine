"""v2 structured model — events, reducer, queue, instructions, queries.

Every write to the structured model goes through
:func:`backend.graph.reducer.append_event`. Every read goes through
:mod:`backend.graph.queries`. Application code does not touch the
projection ORM models directly.

Importing this package also registers the v2 job handlers:
  * ``v2.apply_instructions`` (stub — replaced by later slices)
  * ``v2.generate_feature_expansion``
  * ``v2.mint_features``
  * ``v2.generate_requirements``
  * ``v2.mint_requirements``
"""

from backend.graph import queue as _queue
from backend.graph.handlers import feature_expansion as _feature_expansion_handler
from backend.graph.handlers import feature_mint as _feature_mint_handler
from backend.graph.handlers import requirements_generation as _requirements_gen_handler
from backend.graph.handlers import requirements_mint as _requirements_mint_handler

_queue.register_stub_handler()
_feature_expansion_handler.register()
_feature_mint_handler.register()
_requirements_gen_handler.register()
_requirements_mint_handler.register()
