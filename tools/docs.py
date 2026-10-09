# tools/docs.py
"""Setup guide, credentials manifest and library README, derived from what the generated code actually references."""

import re
from typing import Dict, List

import yaml

from config import TECH_CONFIG
from core.bundle import FileBundle
from core.schemas import PipelineSpec
from tools.groovy_validator import LIB_VARS, collect_references, platform_credentials
from tools.renderer import required_plugins

EXTRA_VARS = {
    "K8S_NAMESPACE_<ENV>": "Optional namespace override per environment (default: <app>-<env>)",
}
CONTROLLER_VARS = {
    "PIPELINE_LIB_REPO_URL": "Git URL of the shared library repository (read by JCasC)",
    "APP_REPO_URL": "Git URL of the application repository (read by the Job DSL seed)",
    "APP_REPO_BRANCH": "Branch the generated jobs build (default main)",
    "SCM_CREDENTIALS_ID": "Optional Jenkins credential ID used to clone the library and application repositories",
}


def _credential_rows(bundle: FileBundle, spec: PipelineSpec) -> List[Dict[str, str]]:
    """One row per Jenkins credential the library expects (cluster credentials expand per environment)."""
    cfg = {"registry": TECH_CONFIG["registries"][spec.registry]["credentials"]["registry"],
           "cluster": TECH_CONFIG["clusters"][spec.cluster]["credentials"]["cluster"]}
    rows: List[Dict[str, str]] = []
    for key, cred_id in sorted(platform_credentials(bundle).items()):
        meta = cfg[key]
        ids = [f"{cred_id}-{e}" for e in spec.environments] if meta.get("per_environment") else [cred_id]
        rows += [{"id": i, "kind": meta["kind"], "description": meta["description"], "value": "<placeholder>"} for i in ids]
    return rows


def _variable_rows(bundle: FileBundle, spec: PipelineSpec) -> List[Dict[str, str]]:
    known = {**TECH_CONFIG["registries"][spec.registry]["vars"], **TECH_CONFIG["clusters"][spec.cluster]["vars"]}
    refs = collect_references(bundle)["vars"]
    unknown = "Referenced by the library; set as needed"
    names = sorted(refs | set(known))
    return [{"name": n, "description": known.get(n, unknown), "value": "<placeholder>"} for n in names]


def credentials_manifest(bundle: FileBundle, spec: PipelineSpec) -> str:
    return yaml.safe_dump(
        {"variables": _variable_rows(bundle, spec), "credentials": _credential_rows(bundle, spec)}, sort_keys=False
    )


def library_readme(bundle: FileBundle, spec: PipelineSpec) -> str:
    lines = []
    for path in sorted(bundle.files):
        if path.startswith(LIB_VARS) and path.endswith(".groovy"):
            first = bundle.files[path].splitlines()[0].lstrip("/ ").strip()
            lines.append(f"| `{path[len(LIB_VARS):-len('.groovy')]}` | {first} |")
    return f"""# {spec.library_name}

Jenkins shared library generated for {len(spec.apps)} application(s). Publish this directory as its own Git repository,
tag it `{spec.library_ref}`, and register it under Manage Jenkins -> System -> Global Trusted Pipeline Libraries
(or let `jenkins/casc/jenkins.yaml` do it).

Application Jenkinsfiles only contain `@Library('{spec.library_name}@{spec.library_ref}') _` plus one call to an
`app*Pipeline` step; all pipeline logic lives here, so a fix ships to every application by moving the tag.

## Steps (`vars/`)

| Step | Purpose |
|---|---|
{chr(10).join(lines)}

`src/org/platform/pipeline/PipelineConfig.groovy` validates the configuration Map each entry point receives.
"""


def setup_guide(bundle: FileBundle, spec: PipelineSpec) -> str:
    reg = TECH_CONFIG["registries"][spec.registry]
    cluster = TECH_CONFIG["clusters"][spec.cluster]
    envs = ", ".join(spec.environments)
    apps = "\n".join(f"- `{a.name}` ({a.tech}) at `{a.path}`" for a in spec.apps)
    protected = ", ".join(e for e in spec.environments if TECH_CONFIG["environments"][e]["approvals"]) or "none"

    def table(headers: str, rows: List[str]) -> str:
        sep = "|".join("---" for _ in headers.split("|"))
        return "\n".join([f"|{headers}|", f"|{sep}|", *rows])

    var_rows = [f"| `{r['name']}` | {r['description']} |" for r in _variable_rows(bundle, spec)]
    var_rows += [f"| `{n}` | {d} |" for n, d in EXTRA_VARS.items()]
    ctl_rows = [f"| `{n}` | {d} |" for n, d in CONTROLLER_VARS.items()]
    cred_rows = [f"| `{r['id']}` | {r['kind']} | {r['description']} |" for r in _credential_rows(bundle, spec)]
    plugins = ", ".join(f"`{p}`" for p in required_plugins(spec))
    return f"""# Jenkins setup

Generated pipeline: **{reg['display']}** registry, **{cluster['display']}**, deployed with **{spec.deploy_method}**.

## Applications
{apps}

Each application gets `jenkins/<app>/Jenkinsfile.validation|build|release`. The Jenkinsfiles are a few lines each;
the logic is in the shared library (`shared-library/`).

## 1. Agents and plugins
- Agents labelled `{spec.agent_label}` need Docker; CI, scanning and deployment all run in pinned containers.
- Plugins ({'`jenkins/plugins.txt`'}): {plugins}.

## 2. Publish the shared library
Push `shared-library/` as its own repository and tag it `{spec.library_ref}`. Jenkinsfiles pin `@{spec.library_ref}`, so a library
change reaches applications only when you move or bump the tag.

## 3. Configure the controller
Set these on the controller environment, copy `jenkins/casc/` to `$JENKINS_HOME/casc/`, and load it with the
Configuration as Code plugin. It registers the library, exposes the variables below and runs the Job DSL seed,
which creates `<app>-validation`, `<app>-build` and `<app>-release`.

{table(' Controller variable | Description ', ctl_rows)}

## 4. Variables (Manage Jenkins -> System -> Global properties, or the controller environment via JCasC)
{table(' Name | Description ', var_rows)}

## 5. Credentials (Manage Jenkins -> Credentials)
{table(' ID | Kind | Description ', cred_rows)}

`credentials-manifest.yaml` lists the same items with `<placeholder>` values for review or automation. Never commit real values.

## 6. Release flow
Build pushes `sha-<commit>`, scans it, then triggers `<app>-release` for `{spec.environments[0]}` with the image **digest**.
Promote further by running the release job with `ENVIRONMENT` set to one of {envs} (or `all`).
Approval prompts (submitter group `{spec.approver_group}`) guard: {protected}. Prompts run without holding an executor.

## 7. Prerequisites
- Registry: create the repository/namespace for each application image{' (ECR repositories must exist before the first push)' if spec.registry == 'ecr' else ''}.
- Cluster: grant the deploy identity rights to create namespaces, Deployments, Services and Secrets.

## 8. Hardening notes
- Pin the library to a tag or commit, and restrict who can push to the library repository: it runs on every pipeline.
- Libraries under *Global Trusted Pipeline Libraries* run outside the Groovy sandbox: require review for every library change.
- Tool images are pinned in `platformConfig`; bump them deliberately.
- The jobs poll SCM every 5 minutes; prefer webhooks, or use multibranch jobs if you want pull-request builds
  (the build pipeline already skips pushing when `CHANGE_ID` is set).
"""


def add_docs(bundle: FileBundle, spec: PipelineSpec) -> None:
    bundle.add("docs/JENKINS_SETUP.md", setup_guide(bundle, spec))
    bundle.add("credentials-manifest.yaml", credentials_manifest(bundle, spec))
    bundle.add("shared-library/README.md", library_readme(bundle, spec))
