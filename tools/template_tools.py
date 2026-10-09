# tools/template_tools.py
"""Agent-callable tools. Each wraps one Renderer method with a narrow, well-described contract."""

from typing import Callable, Dict, List, Set, Tuple

from core.llm import Tool
from tools.renderer import Renderer


class ToolKit:
    """Builds Tool objects bound to one Renderer and records which calls actually happened,
    so the orchestrator can complete anything the model skipped."""

    def __init__(self, renderer: Renderer):
        self.r = renderer
        self.called: Set[Tuple[str, str]] = set()
        self.app_names = sorted(renderer.apps)

    def _per_app(self, name: str, description: str, fn: Callable[[str], List[str]]) -> Tool:
        def run(app_name: str) -> str:
            files = fn(app_name)
            self.called.add((name, app_name))
            return "Wrote: " + ", ".join(files)

        schema = {
            "type": "object",
            "properties": {"app_name": {"type": "string", "enum": self.app_names}},
            "required": ["app_name"],
        }
        return Tool(name, description, schema, run)

    def _global(self, name: str, description: str, fn: Callable[[], List[str]]) -> Tool:
        def run() -> str:
            files = fn()
            self.called.add((name, ""))
            return "Wrote: " + ", ".join(files)

        return Tool(name, description, {"type": "object", "properties": {}}, run)

    def all(self) -> Dict[str, Tool]:
        r = self.r
        tools = [
            # shared library foundation + controller
            self._global("render_library_core", "Create the shared library foundation: platformConfig (credential IDs, pinned tool images, environments), requireEnv, notifyBuild and the PipelineConfig validation class.", r.library_core),
            self._global("render_jenkins_config", "Create controller-side files: JCasC (registers the shared library and platform variables), the Job DSL seed that creates every app's jobs, and the plugin list.", r.jenkins_config),
            # validation
            self._global("render_security_steps", "Create the shared library steps for Trivy scanning and securityScan (gitleaks, hadolint, Trivy filesystem scan).", r.security_steps),
            self._per_app("render_ci_step", "Create the shared library step that runs install, lint, test and build for an app's technology inside a pinned container.", r.ci_step),
            self._global("render_validation_pipeline", "Create the appValidationPipeline library step: the declarative validation pipeline all apps share.", r.validation_pipeline),
            self._per_app("render_validation_jenkinsfile", "Create the app's thin Jenkinsfile.validation that loads the shared library and calls appValidationPipeline.", r.validation_jenkinsfile),
            # build
            self._per_app("render_dockerfile", "Create a multi-stage, non-root Dockerfile and .dockerignore for an app.", r.dockerfile),
            self._global("render_registry_login_step", "Create the registryLogin library step that authenticates to the selected container registry (ACR/ECR/JFrog/Nexus) with Jenkins credentials.", r.registry_login_step),
            self._global("render_build_steps", "Create the shared library steps resolveImage and dockerBuildPush (build, Trivy scan, push immutable sha-<commit> tag).", r.build_steps),
            self._global("render_build_pipeline", "Create the appBuildPipeline library step: the declarative build/scan/push pipeline all apps share.", r.build_pipeline),
            self._per_app("render_build_jenkinsfile", "Create the app's thin Jenkinsfile.build that calls appBuildPipeline.", r.build_jenkinsfile),
            # release
            self._global("render_deploy_steps", "Create the shared library steps for cluster authentication (withK8sContext), namespace preparation, helm/kubectl deployment and deployEnvironment.", r.deploy_steps),
            self._global("render_release_pipeline", "Create the appReleasePipeline library step: environment promotion with approval gates.", r.release_pipeline),
            self._per_app("render_deploy_assets", "Create the Helm chart or kubectl manifests (per environment) for an app.", r.deploy_assets),
            self._per_app("render_release_jenkinsfile", "Create the app's thin Jenkinsfile.release that calls appReleasePipeline.", r.release_jenkinsfile),
        ]
        return {t.name: t for t in tools}

    def select(self, names: List[str]) -> List[Tool]:
        every = self.all()
        return [every[n] for n in names]

    def missing(self, names: List[str]) -> List[Tuple[str, str]]:
        """(tool, app) pairs among `names` the model did not call."""
        out: List[Tuple[str, str]] = []
        every = self.all()
        for n in names:
            per_app = "app_name" in every[n].input_schema["properties"]
            for app in self.app_names if per_app else [""]:
                if (n, app) not in self.called:
                    out.append((n, app))
        return out

    def complete(self, names: List[str]) -> List[Tuple[str, str]]:
        """Run anything in `names` that was never called. Returns what had to be filled in."""
        every = self.all()
        gaps = self.missing(names)
        for n, app in gaps:
            every[n].fn(**({"app_name": app} if app else {}))
        return gaps
