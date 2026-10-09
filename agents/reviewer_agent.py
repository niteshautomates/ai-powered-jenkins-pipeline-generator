# agents/reviewer_agent.py

from typing import List

from config import settings
from core.bundle import FileBundle
from core.llm import observe, parse
from core.schemas import PipelineSpec, ReviewReport

SYSTEM = """You are a senior platform engineer reviewing generated Jenkins pipelines and their shared library.
Check against: credentials only via withCredentials/credentialsId and never interpolated into Groovy strings,
single-quoted sh with environment variables, shared library pinned to a tag, pinned tool images, approval gates
that do not hold an executor, timeouts on pipelines, immutable image reference (digest) for deploys, rollback on
failed deployments, least-privilege cluster/registry credentials, Groovy that is safe under the CPS transformer
(no non-serialisable locals across steps, @NonCPS only for pure helpers), and consistency between Jenkinsfiles,
library steps, JCasC and the Job DSL seed (names, paths, variables, credential IDs). Report only real problems with a
concrete file and fix; do not pad with style nits. Static validator findings are provided - confirm or dismiss them."""

MAX_CHARS = 150_000
REVIEWED = ("shared-library/", "jenkins/")


class ReviewerAgent:
    name = "ReviewerAgent"
    model = settings.MODEL_REVIEWER

    @observe()
    def review(self, spec: PipelineSpec, bundle: FileBundle, validator_issues: List[str]) -> ReviewReport:
        parts, size = [], 0
        for path, content in sorted(bundle.files.items()):
            if not path.startswith(REVIEWED) and not path.endswith("Dockerfile"):
                continue
            chunk = f"=== {path}\n{content}\n"
            if size + len(chunk) > MAX_CHARS:
                break
            parts.append(chunk)
            size += len(chunk)
        task = (
            f"Spec:\n{spec.model_dump_json(indent=2)}\n\nStatic validator findings:\n"
            + ("\n".join(validator_issues) or "none")
            + "\n\nFiles:\n"
            + "".join(parts)
        )
        return parse(self.model, SYSTEM, task, ReviewReport, max_tokens=8000)
