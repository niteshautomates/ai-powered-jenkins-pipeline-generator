import itertools

import pytest
import yaml

from core.bundle import FileBundle
from core.schemas import AppSpec, PipelineSpec
from tools.docs import add_docs
from tools.groovy_validator import collect_references, groovy_code, validate_bundle
from tools.renderer import Renderer
from tools.template_tools import ToolKit

TECHS = ["java", "node", "typescript", "python", "dotnet", "go"]
REGISTRIES = ["acr", "ecr", "jfrog", "nexus"]
CLUSTERS = ["generic", "aks", "eks"]
METHODS = ["helm", "kubectl"]


def generate(apps, **kw) -> FileBundle:
    spec = PipelineSpec(apps=apps, **kw)
    bundle = FileBundle()
    kit = ToolKit(Renderer(spec, bundle))
    kit.complete(list(kit.all()))
    add_docs(bundle, spec)
    return bundle


@pytest.mark.parametrize("tech,registry,cluster,method", list(itertools.product(TECHS, REGISTRIES, CLUSTERS, METHODS)))
def test_matrix_is_valid(tech, registry, cluster, method):
    bundle = generate([AppSpec(name="svc", path="svc", tech=tech)], registry=registry, cluster=cluster, deploy_method=method)
    assert validate_bundle(bundle) == []
    for path, content in bundle.files.items():
        if path.endswith((".yml", ".yaml")) and "/templates/" not in path:
            yaml.safe_load(content)


@pytest.mark.parametrize("notifications", ["none", "slack", "email"])
def test_notification_variants_are_valid(notifications):
    bundle = generate([AppSpec(name="svc", tech="go")], notifications=notifications)
    assert validate_bundle(bundle) == []
    assert ("slackSend" in bundle.files["shared-library/vars/notifyBuild.groovy"]) == (notifications == "slack")


def test_jenkinsfiles_are_thin_and_pin_the_library():
    bundle = generate([AppSpec(name="orders", path="services/orders", tech="java", variant="gradle")], library_ref="v2")
    for kind, entry in (("validation", "appValidationPipeline"), ("build", "appBuildPipeline"), ("release", "appReleasePipeline")):
        text = bundle.files[f"jenkins/orders/Jenkinsfile.{kind}"]
        assert "@Library('platform-pipeline-lib@v2') _" in text
        assert entry in text
        assert "sh " not in text and "pipeline {" not in text  # no logic in the Jenkinsfile
    assert "ciJavaGradle(args)" in bundle.files["jenkins/orders/Jenkinsfile.validation"]
    assert "shared-library/vars/ciJavaGradle.groovy" in bundle.files


def test_multi_app_monorepo_has_per_app_jenkinsfiles_and_shared_steps():
    apps = [AppSpec(name="orders", path="services/orders", tech="java", variant="gradle"),
            AppSpec(name="web", path="web", tech="typescript", variant="yarn")]
    bundle = generate(apps)
    for app in ("orders", "web"):
        for kind in ("validation", "build", "release"):
            assert f"jenkins/{app}/Jenkinsfile.{kind}" in bundle.files
    assert "shared-library/vars/ciTypescriptYarn.groovy" in bundle.files
    assert "services/orders/Dockerfile" in bundle.files
    seed = bundle.files["jenkins/casc/seed.groovy"]
    assert "name: 'orders', path: 'services/orders'" in seed and "name: 'web'" in seed
    assert validate_bundle(bundle) == []


def test_unknown_variant_is_rejected():
    spec = PipelineSpec(apps=[AppSpec(name="x", tech="go", variant="maven")])
    with pytest.raises(ValueError):
        Renderer(spec, FileBundle()).ci_step("x")


def test_toolkit_completes_skipped_calls():
    spec = PipelineSpec(apps=[AppSpec(name="a", tech="go"), AppSpec(name="b", tech="python")])
    kit = ToolKit(Renderer(spec, FileBundle()))
    kit.all()["render_ci_step"].fn(app_name="a")
    assert kit.complete(["render_ci_step"]) == [("render_ci_step", "b")]


def test_release_pipeline_follows_spec_and_gates_protected_environments():
    bundle = generate([AppSpec(name="a", tech="go")], environments=["dev", "prod"], approver_group="ops")
    text = bundle.files["shared-library/vars/appReleasePipeline.groovy"]
    assert "stage('Deploy dev')" in text and "stage('Deploy prod')" in text and "stage('Deploy uat')" not in text
    assert text.count("input {") == 1  # only prod needs approval
    assert "agent none" in text  # approval must not hold an executor
    assert "approverGroup: 'ops'" in bundle.files["shared-library/vars/platformConfig.groovy"]


def test_every_reference_is_documented():
    bundle = generate([AppSpec(name="api", path="api", tech="java")], registry="jfrog", cluster="aks")
    refs = collect_references(bundle)
    manifest = yaml.safe_load(bundle.files["credentials-manifest.yaml"])
    assert refs["vars"] <= {v["name"] for v in manifest["variables"]}
    ids = {c["id"] for c in manifest["credentials"]}
    assert "jfrog-registry" in ids and {"azure-sp-dev", "azure-sp-prod"} <= ids  # cluster credential per environment
    guide = bundle.files["docs/JENKINS_SETUP.md"]
    assert "REGISTRY_HOST" in guide and "AKS_CLUSTER_NAME" in guide and "azure-sp-prod" in guide


def test_deploy_uses_the_selected_method_only():
    helm = generate([AppSpec(name="a", tech="go")], deploy_method="helm")
    kubectl = generate([AppSpec(name="a", tech="go")], deploy_method="kubectl")
    assert "shared-library/vars/deployHelm.groovy" in helm.files and "shared-library/vars/deployKubectl.groovy" not in helm.files
    assert "deployKubectl(" in kubectl.files["shared-library/vars/deployEnvironment.groovy"]
    assert "deploy/k8s/a/prod/deployment.yaml" in kubectl.files


def test_pull_secret_only_for_token_registries():
    assert "docker-registry" in generate([AppSpec(name="a", tech="go")], registry="nexus").files["shared-library/vars/prepareNamespace.groovy"]
    assert "docker-registry" not in generate([AppSpec(name="a", tech="go")], registry="ecr").files["shared-library/vars/prepareNamespace.groovy"]


def test_recommended_kubernetes_labels():
    for method in METHODS:
        bundle = generate([AppSpec(name="svc", path="svc", tech="go")], deploy_method=method)
        text = "\n".join(c for p, c in bundle.files.items() if p.startswith("deploy/"))
        for label in ("name", "instance", "component", "part-of", "managed-by"):
            assert f"app.kubernetes.io/{label}:" in text, (method, label)


# ---- validator ---------------------------------------------------------------------------
def test_groovy_scanner_understands_strings_and_gstrings():
    ok = "def a() { String x = \"v ${m.get('k') ?: \"z\"} {\"; def y = 'it\\'s {'; sh '''echo {''' } // }\n/* ( */"
    assert groovy_code(ok)[1] == []
    assert groovy_code("def a() { foo(")[1]
    assert groovy_code("def a() { 'abc\n }")[1]


def _bundle_with(path: str, content: str) -> FileBundle:
    bundle = generate([AppSpec(name="svc", tech="go")])
    bundle.files[path] = content
    return bundle


@pytest.mark.parametrize("path,content,expected", [
    ("jenkins/svc/Jenkinsfile.build", "@Library('x@main') _\nappBuildPipeline(name: 'svc')\n", "moving ref"),
    ("jenkins/svc/Jenkinsfile.build", "appBuildPipeline(name: 'svc')\n", "missing @Library"),
    ("jenkins/svc/Jenkinsfile.build", "@Library('x@v1') _\nappBuildPipeline(name: 'svc'\n", "never closed"),
    ("jenkins/svc/Jenkinsfile.build", "@Library('x@v1') _\nciRust(name: 'svc')\nappBuildPipeline()\n", "not generated"),
    ("shared-library/vars/bad.groovy", "void call() { sh \"login --password ${PASSWORD}\" }\n", "near a secret"),
    ("shared-library/vars/bad.groovy", "void call() { def password = 'hunter2hunter2' }\n", "hard-coded credential"),
    ("shared-library/vars/bad.groovy", "void call() { sh 'docker pull app:latest' }\n", ":latest"),
    ("shared-library/vars/bad.groovy", "void call() { pipeline { agent any } }\n", "agent any"),
    ("shared-library/vars/bad.groovy", "void call() { echo platformConfig().credentials.nope }\n", "credentials.nope"),
    ("shared-library/vars/bad.groovy", "void call() { deployKubectl() }\n", "deployKubectl"),
    ("shared-library/vars/bad.groovy", "def helper() { 1 }\n", "must define call"),
])
def test_validator_catches_problems(path, content, expected):
    issues = validate_bundle(_bundle_with(path, content))
    assert any(expected in i for i in issues), issues
