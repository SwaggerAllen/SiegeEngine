"""LLM prompt templates for the v2 structured model.

One module per prompt type, each exposing:

* ``SYSTEM_PROMPT: str`` — role, constraints, output format.
* ``render_user_prompt(**inputs) -> str`` — pure string builder with
  the prompt-specific input signature.

Handlers in ``backend.graph.handlers`` import these directly and pass
the rendered strings to ``CLIManager.generate``.
"""
