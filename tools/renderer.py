# tools/renderer.py
"""Deterministic Jinja2 rendering of every generated file. No LLM involved: this is what makes
the output valid and consistent. Agents decide *what* to render; this decides *how*."""

import json
import os
import shlex
from typing import Any, Dict, List

import jinja2

from config import TECH_CONFIG
from core.bundle import FileBundle
from core.schemas import AppSpec, PipelineSpec

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
LIB = "shared-library"  # the shared library is published as its own repository

# Groovy uses `${ }` and Helm uses `{{ }}`, so Jinja uses << >> / <% %> / <# #>.
# (Groovy's `<<` list-append operator must therefore not be used in library templates.)
_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(TEMPLATE_DIR),
    variable_start_string="<<",
    variable_end_string=">>",
    block_start_string="<%",
    block_end_string="%>",
    comment_start_string="<#",
    comment_end_string="#>",
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
    undefined=jinja2.StrictUndefined,
)


def _groovy_single_quoted(value: str) -> str:
    """Escape for use inside a Groovy '...' literal."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


_env.filters["gq"] = _groovy_single_quoted


def ci_step_name(app: AppSpec, variant: str) -> str:
    """Library step name for an app's CI, e.g. ciJavaMaven, ciTypescriptYarn, ciGo."""
    tech = app.tech.capitalize()
    return f"ci{tech}" if variant == app.tech else f"ci{tech}{variant.capitalize()}"


def resolve_app(app: AppSpec) -> Dict[str, Any]:
    """Merge AppSpec with technology defaults into a flat template context."""
    t = TECH_CONFIG["technologies"][app.tech]
    variant = app.variant or t["default_variant"]
    if variant not in t["variants"]:
        raise ValueError(f"{app.tech} has no build variant '{variant}' (choose from {list(t['variants'])})")
    version = app.version or t["default_version"]
    port = app.port or t["default_port"]
    start = app.start_command or t["default_start"]
    if app.tech == "dotnet" and not app.start_command:
        start = f"dotnet {app.name}.dll"
    norm = os.path.normpath(app.path or ".")
    base = "" if norm == "." else norm.strip("/")
    return {
        "app": app,
        "t": t,
        "v": t["variants"][variant],
        "variant": variant,
        "version": version,
        "version_major_minor": ".".join(version.split(".")[:2]),
        "port": port,
        "start_cmd_json": json.dumps(shlex.split(start)),
        "path": base or ".",
        "dockerfile": f"{base}/Dockerfile" if base else "Dockerfile",
        "ci_step": ci_step_name(app, variant),
    }


def required_plugins(spec: PipelineSpec) -> List[str]:
    cfg = TECH_CONFIG["plugins"]
    plugins = list(cfg["base"])
    for key in (spec.registry, spec.cluster, spec.notifications):
        plugins += cfg.get(key, [])
    return list(dict.fromkeys(plugins))


class Renderer:
    """Renders templates for one PipelineSpec into a FileBundle."""

    def __init__(self, spec: PipelineSpec, bundle: FileBundle):
        self.spec = spec
        self.bundle = bundle
        self.apps = {a.name: a for a in spec.apps}
        self.reg = TECH_CONFIG["registries"][spec.registry]

    def _app(self, name: str) -> AppSpec:
        if name not in self.apps:
            raise ValueError(f"Unknown app '{name}'. Known apps: {sorted(self.apps)}")
        return self.apps[name]

    def _render(self, template: str, **ctx: Any) -> str:
        return _env.get_template(template).render(**ctx)

    def _images(self) -> Dict[str, str]:
        tools = TECH_CONFIG["tools"]
        wanted = ["trivy", "hadolint", "gitleaks", "k8s"]
        if self.spec.registry == "ecr":
            wanted.append("aws_cli")
        if self.spec.cluster == "aks":
            wanted.append("azure_cli")
        return {k: tools[k] for k in wanted}

    def _common(self) -> Dict[str, Any]:
        cluster_cfg = TECH_CONFIG["clusters"][self.spec.cluster]
        return {
            "registry": self.spec.registry,
            "reg": self.reg,
            "cluster": self.spec.cluster,
            "cluster_cfg": cluster_cfg,
            "method": self.spec.deploy_method,
            "envs": self.spec.environments,
            "env_cfg": TECH_CONFIG["environments"],
            "approval_envs": [e for e in self.spec.environments if TECH_CONFIG["environments"][e]["approvals"]],
            "agent_label": self.spec.agent_label,
            "library_name": self.spec.library_name,
            "library_ref": self.spec.library_ref,
            "notifications": self.spec.notifications,
            "approver_group": self.spec.approver_group,
            "creds": {"registry": self.reg["credentials"]["registry"], "cluster": cluster_cfg["credentials"]["cluster"]},
            "images": self._images(),
        }

    def _var(self, name: str, **ctx: Any) -> str:
        """Render a library step template (templates/library/vars/<name>.groovy.j2) to shared-library/vars/."""
        path = f"{LIB}/vars/{name}.groovy"
        self.bundle.add(path, self._render(f"library/vars/{name}.groovy.j2", **ctx, **self._common()))
        return path

    # ---- library core / controller ---------------------------------------------------
    def library_core(self) -> List[str]:
        """Foundation of the shared library: platform conventions, env lookup, notifications, config validation."""
        written = [self._var(n) for n in ("platformConfig", "requireEnv", "notifyBuild")]
        path = f"{LIB}/src/org/platform/pipeline/PipelineConfig.groovy"
        self.bundle.add(path, self._render("library/src/org/platform/pipeline/PipelineConfig.groovy.j2"))
        return written + [path]

    def jenkins_config(self) -> List[str]:
        """Controller-side files: JCasC (library + variables), Job DSL seed, plugin list."""
        c = self._common()
        var_names = sorted({**self.reg["vars"], **c["cluster_cfg"]["vars"]})
        files = {
            "jenkins/casc/jenkins.yaml": self._render("jenkins/casc.yaml.j2", **c, var_names=var_names),
            "jenkins/casc/seed.groovy": self._render(
                "jenkins/seed.groovy.j2", **c, apps=[resolve_app(a) | {"name": a.name} for a in self.spec.apps]
            ),
            "jenkins/plugins.txt": self._render("jenkins/plugins.txt.j2", plugins=required_plugins(self.spec)),
        }
        for path, content in files.items():
            self.bundle.add(path, content)
        return list(files)

    # ---- validation ------------------------------------------------------------------
    def security_steps(self) -> List[str]:
        return [self._var("trivyScan"), self._var("securityScan")]

    def ci_step(self, app_name: str) -> List[str]:
        ctx = resolve_app(self._app(app_name))
        path = f"{LIB}/vars/{ctx['ci_step']}.groovy"
        self.bundle.add(path, self._render("library/vars/ciStep.groovy.j2", **ctx))
        return [path]

    def validation_pipeline(self) -> List[str]:
        return [self._var("appValidationPipeline")]

    def validation_jenkinsfile(self, app_name: str) -> List[str]:
        ctx = resolve_app(self._app(app_name))
        path = f"jenkins/{app_name}/Jenkinsfile.validation"
        self.bundle.add(path, self._render("jenkinsfiles/validation.j2", **ctx, **self._common()))
        return [path]

    # ---- build -----------------------------------------------------------------------
    def dockerfile(self, app_name: str) -> List[str]:
        ctx = resolve_app(self._app(app_name))
        prefix = "" if ctx["path"] == "." else ctx["path"] + "/"
        files = [f"{prefix}Dockerfile", f"{prefix}.dockerignore"]
        self.bundle.add(files[0], self._render("docker/Dockerfile.j2", **ctx))
        self.bundle.add(files[1], self._render("docker/dockerignore.j2", **ctx))
        return files

    def registry_login_step(self) -> List[str]:
        return [self._var("registryLogin")]

    def build_steps(self) -> List[str]:
        return [self._var("resolveImage"), self._var("dockerBuildPush")]

    def build_pipeline(self) -> List[str]:
        return [self._var("appBuildPipeline")]

    def build_jenkinsfile(self, app_name: str) -> List[str]:
        ctx = resolve_app(self._app(app_name))
        path = f"jenkins/{app_name}/Jenkinsfile.build"
        self.bundle.add(path, self._render("jenkinsfiles/build.j2", **ctx, **self._common()))
        return [path]

    # ---- release ---------------------------------------------------------------------
    def deploy_steps(self) -> List[str]:
        """Cluster auth, namespace preparation, helm/kubectl deployment and the per-environment deploy step."""
        names = ["resolveImage", "withK8sContext", "prepareNamespace", f"deploy{self.spec.deploy_method.capitalize()}",
                 "deployEnvironment"]
        return [self._var(n) for n in names]

    def release_pipeline(self) -> List[str]:
        return [self._var("appReleasePipeline")]

    def release_jenkinsfile(self, app_name: str) -> List[str]:
        ctx = resolve_app(self._app(app_name))
        path = f"jenkins/{app_name}/Jenkinsfile.release"
        self.bundle.add(path, self._render("jenkinsfiles/release.j2", **ctx, **self._common()))
        return [path]

    def deploy_assets(self, app_name: str) -> List[str]:
        ctx = resolve_app(self._app(app_name))
        written: List[str] = []
        if self.spec.deploy_method == "helm":
            root = f"deploy/helm/{app_name}"
            self.bundle.add(f"{root}/Chart.yaml", self._render("helm/Chart.yaml.j2", **ctx))
            self.bundle.add(f"{root}/values.yaml", self._render("helm/values.yaml.j2", **ctx))
            written += [f"{root}/Chart.yaml", f"{root}/values.yaml"]
            for env in self.spec.environments:
                p = f"{root}/values-{env}.yaml"
                replicas = TECH_CONFIG["environments"][env]["replicas"]
                self.bundle.add(p, self._render("helm/values-env.yaml.j2", **ctx, env=env, replicas=replicas))
                written.append(p)
            helm_dir = os.path.join(TEMPLATE_DIR, "helm", "templates")
            for name in sorted(os.listdir(helm_dir)):
                with open(os.path.join(helm_dir, name)) as f:
                    self.bundle.add(f"{root}/templates/{name}", f.read())
                written.append(f"{root}/templates/{name}")
        else:
            for env in self.spec.environments:
                replicas = TECH_CONFIG["environments"][env]["replicas"]
                for kind in ("deployment", "service"):
                    p = f"deploy/k8s/{app_name}/{env}/{kind}.yaml"
                    self.bundle.add(
                        p,
                        self._render(
                            f"k8s/{kind}.yaml.j2", **ctx, env=env, replicas=replicas,
                            placeholder_image="IMAGE_PLACEHOLDER",
                        ),
                    )
                    written.append(p)
        return written
