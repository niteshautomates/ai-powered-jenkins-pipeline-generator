# core/schemas.py
"""Typed pipeline specification produced by the planner and consumed by every agent."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

Tech = Literal["java", "node", "typescript", "python", "dotnet", "go"]
Registry = Literal["acr", "ecr", "jfrog", "nexus"]
Cluster = Literal["generic", "aks", "eks"]
DeployMethod = Literal["kubectl", "helm"]
EnvName = Literal["dev", "test", "uat", "prod"]
Notifications = Literal["none", "slack", "email"]


class AppSpec(BaseModel):
    name: str = Field(description="Lowercase kebab-case application name, e.g. orders-api")
    path: str = Field(default=".", description="Directory of the app relative to repo root")
    tech: Tech
    variant: Optional[str] = Field(
        default=None, description="Build tool: maven|gradle, npm|yarn, pip|poetry. Omit for default"
    )
    version: Optional[str] = Field(default=None, description="Runtime version, e.g. 21, 20, 3.12")
    port: Optional[int] = Field(default=None, description="Container port; omit for the tech default")
    start_command: Optional[str] = Field(
        default=None, description="Container start command, e.g. 'node dist/server.js'; omit for tech default"
    )


class PipelineSpec(BaseModel):
    apps: List[AppSpec]
    registry: Registry = "ecr"
    cluster: Cluster = "generic"
    deploy_method: DeployMethod = "helm"
    environments: List[EnvName] = Field(default_factory=lambda: ["dev", "test", "uat", "prod"])
    agent_label: str = Field(default="docker", description="Jenkins agent label; agents need Docker")
    library_name: str = Field(default="platform-pipeline-lib", description="Jenkins shared library name")
    library_ref: str = Field(default="v1", description="Library tag or branch pinned by Jenkinsfiles")
    notifications: Notifications = "none"
    approver_group: str = Field(
        default="release-managers", description="Jenkins user/group allowed to approve uat/prod deployments"
    )
    reasoning: str = Field(default="", description="One or two sentences on how the spec was derived")


class Finding(BaseModel):
    severity: Literal["high", "medium", "low"]
    file: str
    issue: str
    suggestion: str


class ReviewReport(BaseModel):
    summary: str
    findings: List[Finding] = Field(default_factory=list)
