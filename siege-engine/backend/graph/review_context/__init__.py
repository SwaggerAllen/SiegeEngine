"""Per-tier shared context builders.

Each tier's generation handler inlined its context-assembly
block before Phase 8. With reviews landing, the reviewer needs
exactly the same bundle the generator saw — so these modules
lift those assembly blocks into reusable
``gather_<tier>_context`` functions. The generator calls them,
the reviewer calls them, zero drift.

One submodule per tier. Each exports a dataclass carrying every
prompt-ready string the generator renders plus any auxiliary
fields the validator or handler needs (e.g. ``known_*_ids``).
"""
