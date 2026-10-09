# tools/repo_scanner.py
"""Detect applications and their technology by looking at build files. Read-only, no LLM."""

import json
import os
import re
from typing import Any, Dict, List, Optional

SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "target", "build", "dist", "bin", "obj", "__pycache__", ".github", "jenkins", "shared-library"}
MAX_DEPTH = 3


def _read(path: str) -> str:
    try:
        with open(path, "r", errors="ignore") as f:
            return f.read()
    except OSError:
        return ""


def _detect(directory: str, files: List[str]) -> Optional[Dict[str, Any]]:
    names = set(files)
    join = lambda n: os.path.join(directory, n)  # noqa: E731

    if "pom.xml" in names:
        m = re.search(r"<java.version>(\d+)</java.version>|<maven.compiler.release>(\d+)<", _read(join("pom.xml")))
        return {"tech": "java", "variant": "maven", "version": (m.group(1) or m.group(2)) if m else None}
    if names & {"build.gradle", "build.gradle.kts"}:
        return {"tech": "java", "variant": "gradle", "version": None}
    if "package.json" in names:
        try:
            pkg = json.loads(_read(join("package.json")))
        except ValueError:
            pkg = {}
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        is_ts = "tsconfig.json" in names or "typescript" in deps
        engines = pkg.get("engines", {}).get("node", "")
        m = re.search(r"(\d+)", engines)
        variant = "yarn" if "yarn.lock" in names else "npm"
        start = None
        if "start" in pkg.get("scripts", {}):
            start = "npm start" if variant == "npm" else "yarn start"
        return {
            "tech": "typescript" if is_ts else "node", "variant": variant,
            "version": m.group(1) if m else None, "start_command": start, "name": pkg.get("name"),
        }
    csproj = [n for n in files if n.endswith(".csproj")]
    if csproj:
        m = re.search(r"<TargetFramework>net(\d+\.\d+)</TargetFramework>", _read(join(csproj[0])))
        project = csproj[0][: -len(".csproj")]
        return {
            "tech": "dotnet", "variant": "dotnet", "version": f"{m.group(1)}.x" if m else None,
            "start_command": f"dotnet {project}.dll",
        }
    if "go.mod" in names:
        m = re.search(r"^go\s+(\d+\.\d+)", _read(join("go.mod")), re.M)
        return {"tech": "go", "variant": "go", "version": m.group(1) if m else None}
    if names & {"requirements.txt", "pyproject.toml"}:
        poetry = "pyproject.toml" in names and "[tool.poetry]" in _read(join("pyproject.toml"))
        entry = next((n for n in ("main.py", "app.py", "manage.py") if n in names), None)
        return {
            "tech": "python", "variant": "poetry" if poetry else "pip", "version": None,
            "start_command": f"python {entry}" if entry else None,
        }
    return None


def scan_repo(root: str) -> List[Dict[str, Any]]:
    """Return one entry per detected application: {path, name, tech, variant, version, start_command}."""
    root = os.path.abspath(root)
    found: List[Dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        dirnames[:] = [d for d in sorted(dirnames) if d not in SKIP_DIRS and not d.startswith(".")]
        hit = _detect(dirpath, filenames)
        if hit:
            hit["path"] = rel
            hit["name"] = re.sub(r"[^a-z0-9-]", "-", (hit.get("name") or os.path.basename(dirpath)).lower()).strip("-")
            found.append({k: v for k, v in hit.items() if v is not None})
            dirnames[:] = []  # an app directory is a leaf
        elif depth >= MAX_DEPTH:
            dirnames[:] = []
    return found
