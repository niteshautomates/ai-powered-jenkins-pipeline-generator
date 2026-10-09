# agents/base_agent.py

import logging
from typing import Any, Dict, List, Optional

from core.llm import observe, run_with_tools
from core.schemas import PipelineSpec
from tools.template_tools import ToolKit

logger = logging.getLogger(__name__)


class BaseAgent:
    """An agent = a model, a system prompt, and a small set of narrowly-scoped tools.

    The model chooses which tools to call; the tools render deterministic output. Anything the model
    skips is completed afterwards, so a weak run degrades to "less clever" rather than "incomplete"."""

    name = "BaseAgent"
    model = ""
    system_prompt = ""
    tool_names: List[str] = []

    def __init__(self, toolkit: ToolKit, use_llm: bool = True):
        self.toolkit = toolkit
        self.use_llm = use_llm

    def build_task(self, spec: PipelineSpec) -> str:
        raise NotImplementedError

    @observe()
    def execute(self, spec: PipelineSpec) -> Dict[str, Any]:
        summary: Optional[str] = None
        if self.use_llm:
            summary = run_with_tools(
                self.model, self.system_prompt, self.build_task(spec), self.toolkit.select(self.tool_names)
            )
        gaps = self.toolkit.complete(self.tool_names)
        if gaps and self.use_llm:
            logger.warning("%s: completed %d skipped tool call(s) deterministically", self.name, len(gaps))
        return {
            "agent": self.name,
            "model": self.model if self.use_llm else None,
            "summary": summary,
            "filled_by_fallback": [f"{t}({a})" if a else t for t, a in gaps],
        }
