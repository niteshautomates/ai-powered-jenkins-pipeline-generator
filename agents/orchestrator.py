# agents/orchestrator.py

import logging
from typing import Any, Dict, Optional

from agents.build_agent import BuildAgent
from agents.library_agent import LibraryAgent
from agents.planner_agent import PlannerAgent
from agents.release_agent import ReleaseAgent
from agents.reviewer_agent import ReviewerAgent
from agents.validation_agent import ValidationAgent
from core.bundle import FileBundle
from core.llm import flush, langfuse_context, observe
from core.schemas import PipelineSpec
from tools.docs import add_docs
from tools.renderer import Renderer
from tools.template_tools import ToolKit
from tools.groovy_validator import validate_bundle

logger = logging.getLogger(__name__)


class OrchestratorAgent:
    """planner -> library -> validation -> build -> release -> docs -> static validation -> LLM review."""

    name = "OrchestratorAgent"

    @observe(name="jenkins-pipeline-generation")
    def run(
        self,
        request: str = "",
        repo_path: Optional[str] = None,
        diagram_path: Optional[str] = None,
        spec: Optional[PipelineSpec] = None,
        use_llm: bool = True,
        review: bool = True,
    ) -> Dict[str, Any]:
        langfuse_context.update_current_trace(name="jenkins-pipeline-generation", input=request or "spec")

        if spec is None:
            if not use_llm:
                raise ValueError("A PipelineSpec is required when running without an LLM")
            spec = PlannerAgent().plan(request, repo_path, diagram_path)
        if not spec.apps:
            raise ValueError(
                "No applications were identified. Pass --repo <path> to scan a repository, or name each "
                "application's technology and path in the request (or supply --spec)."
            )
        logger.info("Plan: %s", spec.model_dump_json())

        bundle = FileBundle()
        toolkit = ToolKit(Renderer(spec, bundle))
        reports = [
            agent(toolkit, use_llm=use_llm).execute(spec)
            for agent in (LibraryAgent, ValidationAgent, BuildAgent, ReleaseAgent)
        ]
        add_docs(bundle, spec)

        issues = validate_bundle(bundle)
        report = ReviewerAgent().review(spec, bundle, issues) if (use_llm and review) else None
        flush()
        return {"spec": spec, "bundle": bundle, "agent_reports": reports, "validator_issues": issues, "review": report}
