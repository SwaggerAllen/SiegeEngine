from backend.pipeline.prompts.base import PromptTemplate


class SystemRequirementsPrompt(PromptTemplate):

    def build(self, input_artifacts, component_key=None, feedback=None, human_notes=None, prompt_config=None):
        if prompt_config:
            return self._build_from_config(input_artifacts, component_key, feedback, human_notes, prompt_config)

        project_doc = input_artifacts.get("project_doc", "")
        messages = [
            {"role": "system", "content": self.full_system_message},
            {"role": "user", "content": f"PROJECT DOCUMENT:\n\n{project_doc}"},
        ]
        return self._inject_feedback(messages, feedback, human_notes)


class ComponentRequirementsPrompt(PromptTemplate):

    def build(self, input_artifacts, component_key=None, feedback=None, human_notes=None, prompt_config=None):
        if prompt_config:
            return self._build_from_config(input_artifacts, component_key, feedback, human_notes, prompt_config)

        system_arch = input_artifacts.get("system_architecture", "")
        system_reqs = input_artifacts.get("system_requirements", "")
        context_parts = []
        if system_reqs:
            context_parts.append(f"SYSTEM REQUIREMENTS:\n\n{system_reqs}")
        if system_arch:
            context_parts.append(f"SYSTEM ARCHITECTURE:\n\n{system_arch}")
        dep_archs = input_artifacts.get("dependency_architectures", "")
        if dep_archs:
            context_parts.append(f"DEPENDENCY COMPONENT ARCHITECTURES:\n\n{dep_archs}")

        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": "\n\n---\n\n".join(context_parts)
                + f"\n\nCOMPONENT: {component_key}\n\n"
                "Produce detailed requirements for this component.",
            },
        ]
        return self._inject_feedback(messages, feedback, human_notes)
