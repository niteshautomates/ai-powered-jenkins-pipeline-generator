# AI-Powered Jenkins Pipeline Generator

Multi-agent, multi-modal generator (Anthropic SDK + Langfuse) that produces **Jenkins pipelines built on a shared library**
for polyglot repos (Java, Node.js, TypeScript, Python, .NET, Go). It is the Jenkins counterpart of
`ai-powered-github-actions-generator` and keeps the same principle:

**Claude plans, chooses tools and reviews. Jinja2 templates write the Groovy/YAML**, so output is consistent and statically checked.

## What it generates

| Output | Contents |
|---|---|
| `shared-library/` | A Jenkins shared library (publish as its own repo). `vars/`: `appValidationPipeline`, `appBuildPipeline`, `appReleasePipeline` (declarative pipelines), per-technology `ci<Tech><Tool>` steps, `securityScan`, `trivyScan`, `registryLogin`, `dockerBuildPush`, `resolveImage`, `withK8sContext`, `prepareNamespace`, `deployHelm`/`deployKubectl`, `deployEnvironment`, `notifyBuild`, `platformConfig`, `requireEnv`. `src/`: `PipelineConfig` input validation. |
| `jenkins/<app>/Jenkinsfile.{validation,build,release}` | A few lines each: `@Library('platform-pipeline-lib@v1') _` plus one `app*Pipeline(...)` call. No pipeline logic, so a fix ships to every app by moving the library tag. |
| `jenkins/casc/` + `jenkins/plugins.txt` | JCasC (registers the library, exposes platform variables), Job DSL seed creating `<app>-validation|build|release` jobs with per-app path filters, plugin list. |
| App repo files | Dockerfile + `.dockerignore`, Helm chart with per-env values (or per-env kubectl manifests). |
| `docs/JENKINS_SETUP.md`, `credentials-manifest.yaml`, `shared-library/README.md` | Derived from what the generated code actually references (every `requireEnv(...)` variable and credential ID). |

Pipeline behaviour: validation = containerised install/lint/test/build + gitleaks, hadolint, Trivy fs scan (parallel).
Build = docker build, Trivy image scan, push of immutable `sha-<commit>` (never pushed for PRs), then triggers the release job with the image **digest**.
Release = `dev -> test -> uat -> prod` as declarative stages; `uat`/`prod` use `input` approvals under `agent none` (no executor held), Helm `--atomic` or kubectl with `rollout undo`.
Registries: ACR / ECR / JFrog / Nexus. Clusters: kubeconfig credential, AKS (service principal), EKS (AWS credentials). All via Jenkins credentials; no secret is interpolated into a Groovy string.

## Agents and models

| Agent | Default model | Job |
|---|---|---|
| Planner | `claude-haiku-5-5` (`claude-sonnet-5-5` when a diagram image is given) | Request + repo scan + diagram -> `PipelineSpec` (structured output) |
| Library / Validation / Build / Release | `claude-sonnet-5-5` | Tool-calling loops over narrow render tools; skipped calls are completed deterministically |
| Reviewer | `claude-opus-5-5` | Reviews the bundle against a Jenkins security/ops checklist |

Override with `MODEL_PLANNER`, `MODEL_VISION`, `MODEL_GENERATOR`, `MODEL_REVIEWER`. Set Langfuse keys to trace each run.

## Usage

```bash
python3.12 -m venv .venv && source .venv/bin/activate   # anthropic 1.x needs Python 3.10+
pip install -r requirements.txt
cp .env.example .env                                    # add ANTHROPIC_API_KEY

# Natural language + repo scan
python main.py -r "ACR, AKS, Helm, Slack notifications" --repo ../my-monorepo -o out

# Architecture diagram (multi-modal)
python main.py -r "Generate Jenkins pipelines for this architecture" --diagram arch.png -o out

# No LLM: deterministic from a spec file
python main.py --no-llm --spec spec.json -o out
```

`spec.json` example (extra fields: `agent_label`, `library_name`, `library_ref`, `notifications`, `approver_group`):
```json
{"apps": [{"name": "orders", "path": "services/orders", "tech": "java", "variant": "maven"}],
 "registry": "acr", "cluster": "aks", "deploy_method": "helm", "library_ref": "v1"}
```

Then follow `out/docs/JENKINS_SETUP.md` (publish library, configure controller, create variables and credentials).

## Layout

```
agents/     planner, library, validation, build, release, reviewer, orchestrator
core/       llm (Anthropic + Langfuse), schemas, file bundle
tools/      renderer, agent tools, repo scanner, Groovy/YAML validator, docs generator
templates/  library/ (vars, src), jenkinsfiles/, jenkins/ (JCasC, seed, plugins), docker/, helm/, k8s/
config/     settings, technology_config.yaml (commands, CI images, pinned tool images, registries, clusters)
tests/      pytest (no network; LLM faked)
```
Templates use `<< >>` / `<% %>` delimiters so Groovy `${ }` and Helm `{{ }}` pass through; do not use Groovy's `<<` operator in library templates.

## Tests

```bash
python -m pytest -q
```

## Known limits
- Not run against a live Jenkins or a live Anthropic call. No Groovy runtime was available: the validator scans strings, comments, GStrings and brackets, checks step/credential references and security policy, but does not compile Groovy. Smoke-test with JenkinsPipelineUnit or a scratch controller before rollout.
- The GitHub generator's CodeQL, dependency review and canary/blue-green strategies have no direct Jenkins equivalent here; Trivy fs scan covers dependencies, and deployment is rolling (Helm `--atomic` / kubectl with `rollout undo`).
- Jobs are plain pipeline jobs polling SCM, not multibranch (SCM-specific). The build pipeline already skips pushing when `CHANGE_ID` is set, so switching to multibranch works.
- Start command defaults per technology (`npm start`, `python main.py`, `dotnet <app>.dll`, ...); set `start_command` in the spec if yours differs.
- AAD-enabled AKS clusters may need `kubelogin` in the Azure CLI step.
