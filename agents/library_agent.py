# agents/library_agent.py

from agents.base_agent import BaseAgent
from config import settings
from core.schemas import PipelineSpec


class LibraryAgent(BaseAgent):
    """Generates the shared library foundation and the controller-side configuration (JCasC, Job DSL seed, plugins)."""

    name = "LibraryAgent"
    model = settings.MODEL_GENERATOR
    tool_names = ["render_library_core", "render_jenkins_config"]
    system_prompt = (
        "You set up a Jenkins shared library and controller configuration by calling tools. Never write Groovy or YAML "
        "yourself. Call render_library_core once, then render_jenkins_config once. Finish with a one-paragraph summary."
    )

    def build_task(self, spec: PipelineSpec) -> str:
        apps = ", ".join(a.name for a in spec.apps)
        return (
            f"Library '{spec.library_name}@{spec.library_ref}', registry {spec.registry}, cluster {spec.cluster}, "
            f"notifications {spec.notifications}. Applications: {apps}."
        )
