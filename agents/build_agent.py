# agents/build_agent.py

from agents.base_agent import BaseAgent
from config import settings
from core.schemas import PipelineSpec


class BuildAgent(BaseAgent):
    """Generates Dockerfiles, registry login, the image build/scan/push steps and the build pipeline."""

    name = "BuildAgent"
    model = settings.MODEL_GENERATOR
    tool_names = [
        "render_registry_login_step", "render_build_steps", "render_build_pipeline",
        "render_dockerfile", "render_build_jenkinsfile",
    ]
    system_prompt = (
        "You generate container build pipelines for Jenkins by calling tools. Never write Groovy or Dockerfiles yourself. "
        "Call render_registry_login_step, render_build_steps and render_build_pipeline once, then for every application "
        "call render_dockerfile and render_build_jenkinsfile. Finish with a one-paragraph summary."
    )

    def build_task(self, spec: PipelineSpec) -> str:
        apps = "\n".join(f"- {a.name} ({a.tech})" for a in spec.apps)
        return f"Registry: {spec.registry}. Create build assets for:\n{apps}"
