"""Per-tier AI self-review prompt templates.

One module per tier. Each exports ``render_system_prompt()`` +
``render_user_prompt(context, generated_output)``. The system
prompt frames the reviewer's job; the user prompt bundles the
same context the generator saw, the generator's output, and a
fixed two-section instruction ("handles & structure" +
"architectural decisions") that the frontend renders as one
collapsible markdown block.
"""
