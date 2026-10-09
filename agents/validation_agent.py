# agents/validation_agent.py

from agents.base_agent import BaseAgent
from config import settings
from core.schemas import PipelineSpec


class ValidationAgent(BaseAgent):
    """Generates validation assets: security steps, per-technology CI steps, the validation pipeline and Jenkinsfiles."""

    name = "ValidationAgent"
    model = settings.MODEL_GENERATOR
    tool_names = ["render_security_steps", "render_ci_step", "render_validation_pipeline", "render_validation_jenkinsfile"]
    system_prompt = (
        "You generate Jenkins validation pipelines by calling tools. Never write Groovy yourself. "
        "Call render_security_steps and render_validation_pipeline once. For every application call render_ci_step "
        "first, then render_validation_jenkinsfile. Finish with a one-paragraph summary of what was created."
    )

    def build_task(self, spec: PipelineSpec) -> str:
        apps = "\n".join(f"- {a.name} ({a.tech})" for a in spec.apps)
        return f"Create validation assets for these applications:\n{apps}"
