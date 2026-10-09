# agents/release_agent.py

from agents.base_agent import BaseAgent
from config import settings
from core.schemas import PipelineSpec


class ReleaseAgent(BaseAgent):
    """Generates the deploy steps, the release pipeline, per-app Jenkinsfiles and Helm/kubectl assets."""

    name = "ReleaseAgent"
    model = settings.MODEL_GENERATOR
    tool_names = ["render_deploy_steps", "render_release_pipeline", "render_deploy_assets", "render_release_jenkinsfile"]
    system_prompt = (
        "You generate Kubernetes release pipelines for Jenkins by calling tools. Never write Groovy or YAML yourself. "
        "Call render_deploy_steps and render_release_pipeline once, then for every application call render_deploy_assets "
        "and render_release_jenkinsfile. Finish with a one-paragraph summary."
    )

    def build_task(self, spec: PipelineSpec) -> str:
        apps = ", ".join(a.name for a in spec.apps)
        return (
            f"Deployment method: {spec.deploy_method} on {spec.cluster}. "
            f"Environments: {', '.join(spec.environments)}. Applications: {apps}."
        )
