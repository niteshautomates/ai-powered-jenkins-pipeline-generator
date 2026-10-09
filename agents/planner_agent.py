# agents/planner_agent.py

import json
import os
from typing import Any, Dict, List, Optional

from config import settings
from core.llm import image_block, observe, parse
from core.schemas import PipelineSpec
from tools.repo_scanner import scan_repo

SYSTEM = """You turn a CI/CD request into a PipelineSpec for Jenkins pipelines built on a shared library.
- Use the repository scan (if provided) as ground truth for application paths, technology and build tool.
- Use an architecture diagram (if provided) to identify services, registry and cluster.
- Registry is one of acr, ecr, jfrog, nexus. Cluster: aks for Azure, eks for AWS, otherwise generic.
- Deploy method is helm or kubectl. Default environments: dev, test, uat, prod.
- Set agent_label, library_name, library_ref, notifications (none, slack, email) and approver_group only when the
  request states them; otherwise leave the defaults.
- App names are lowercase kebab-case and unique. Do not invent applications that are not in the request,
  scan or diagram. When something is unspecified, leave the field at its default."""


class PlannerAgent:
    name = "PlannerAgent"

    @observe()
    def plan(self, request: str, repo_path: Optional[str] = None, diagram_path: Optional[str] = None) -> PipelineSpec:
        content: List[Dict[str, Any]] = []
        model = settings.MODEL_PLANNER
        if diagram_path:
            if not os.path.isfile(diagram_path):
                raise FileNotFoundError(diagram_path)
            content.append(image_block(diagram_path))
            model = settings.MODEL_VISION  # multi-modal input needs the stronger vision model
        text = f"Request: {request}"
        if repo_path:
            text += f"\n\nRepository scan:\n{json.dumps(scan_repo(repo_path), indent=2)}"
        content.append({"type": "text", "text": text})
        return parse(model, SYSTEM, content, PipelineSpec)
