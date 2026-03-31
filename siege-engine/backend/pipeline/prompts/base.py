from abc import ABC, abstractmethod


class PromptTemplate(ABC):
    """Base prompt template. Subclasses define default prompts."""

    # Defaults are loaded from defaults.yaml at import time via __init__.py.
    # These empty strings serve as fallbacks if YAML loading is skipped.
    default_system_message: str = ""
    default_output_format: str = ""
    default_context_template: str = "{input_artifacts}"
    default_revision_instructions: str = ""
    formatting_guidance: str = ""

    @property
    def full_system_message(self) -> str:
        """System message + output format instructions + formatting guidance combined."""
        parts = [self.default_system_message]
        if self.default_output_format:
            parts.append(self.default_output_format)
        parts.append(self.formatting_guidance)
        return "\n\n".join(parts)

    @abstractmethod
    def build(
        self,
        input_artifacts: dict[str, str],
        component_key: str | None = None,
        human_notes: str | None = None,
        prompt_config: dict | None = None,
        current_content: str | None = None,
        upstream_changes: str | None = None,
    ) -> list[dict]: ...

    def _build_from_config(
        self,
        input_artifacts: dict[str, str],
        component_key: str | None,
        human_notes: str | None,
        prompt_config: dict,
        current_content: str | None = None,
        upstream_changes: str | None = None,
    ) -> list[dict]:
        """Build messages from a PromptConfig (DB-stored configuration)."""
        system_msg = prompt_config.get("system_message") or self.default_system_message
        output_fmt = prompt_config.get("output_format_instructions") or self.default_output_format
        ctx_template = prompt_config.get("context_template") or self.default_context_template

        if output_fmt:
            system_msg = f"{system_msg}\n\n{output_fmt}"

        # Always append formatting guidance
        system_msg = f"{system_msg}\n\n{self.formatting_guidance}"

        # Build the context from template
        artifacts_text = "\n\n".join(f"### {k}\n{v}" for k, v in input_artifacts.items())
        user_content = ctx_template.replace("{input_artifacts}", artifacts_text)
        if component_key:
            user_content = user_content.replace("{component_key}", component_key)

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_content},
        ]

        if human_notes or current_content or upstream_changes:
            revision = (
                prompt_config.get("revision_instructions") or self.default_revision_instructions
            )
            if current_content:
                revision += (
                    "\n\nHere is your previous output. Revise it to address the issues below. "
                    "Keep unchanged sections intact — only modify what needs to change.\n\n"
                    f"CURRENT DOCUMENT:\n\n{current_content}"
                )
            if upstream_changes:
                revision += (
                    "\n\nThe following upstream documents have changed:\n\n"
                    f"UPSTREAM CHANGES:\n\n{upstream_changes}"
                )
            if human_notes:
                revision += f"\n\nHuman Reviewer Notes: {human_notes}"
            messages.append({"role": "user", "content": revision})

        return messages

    def _inject_feedback(
        self,
        messages: list[dict],
        human_notes: str | None,
        current_content: str | None = None,
        upstream_changes: str | None = None,
    ) -> list[dict]:
        if not (human_notes or current_content or upstream_changes):
            return messages

        revision_parts = ["REVISION REQUESTED."]

        if current_content:
            revision_parts.append(
                "Here is your previous output. Revise it to address the issues below. "
                "Keep unchanged sections intact — only modify what needs to change.\n\n"
                f"CURRENT DOCUMENT:\n\n{current_content}"
            )

        if upstream_changes:
            revision_parts.append(
                "The following upstream documents have changed since your last output:\n\n"
                f"UPSTREAM CHANGES:\n\n{upstream_changes}\n\n"
                "Update your document to reflect these upstream changes."
            )

        if human_notes:
            revision_parts.append(f"Human Reviewer Notes: {human_notes}")

        if not current_content and not upstream_changes:
            revision_parts.append("Address all issues and produce an improved version.")

        messages.append({"role": "user", "content": "\n\n".join(revision_parts)})
        return messages
