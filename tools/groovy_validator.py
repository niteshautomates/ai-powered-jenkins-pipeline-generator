# tools/groovy_validator.py
"""Static checks over the generated bundle. Cheap, deterministic, run before the LLM reviewer.

No Groovy runtime is assumed: a small scanner understands comments, '..' / ".." / '''..''' / \"\"\"..\"\"\"
strings and GString `${ }` interpolation, which is enough to catch unbalanced brackets and unterminated strings,
and the remaining checks are Jenkins-specific policy (references, credentials, secret handling)."""

import os
import re
from typing import Dict, List, Set, Tuple

import yaml

from core.bundle import FileBundle

LIB_VARS = "shared-library/vars/"
TEMPLATE_VARS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates", "library", "vars")
PAIRS = {")": "(", "]": "[", "}": "{"}
MOVING_REFS = {"main", "master", "latest", "head", "develop"}

LIBRARY_ANNOTATION = re.compile(r"^\s*@Library\(\s*'([^'@]+)@([^']+)'\s*\)\s*_", re.M)
REQUIRE_ENV = re.compile(r"requireEnv\('([A-Z][A-Z0-9_]*)'")
CRED_KEY = re.compile(r"\bcredentials\.([A-Za-z_]\w*)")
HARDCODED_SECRET = re.compile(r"(?i)\b(?:password|passwd|secret|token)\b\s*[:=]\s*['\"][^'\"$]{4,}['\"]|AKIA[0-9A-Z]{16}")
DQ_SH_WITH_SECRET = re.compile(r"\bsh\s*\(?\s*\"[^\n]*(?i:password|token|secret)")


def _scan(src: str, i: int, errors: List[str], nested: bool) -> Tuple[int, str]:
    """Scan code from i. Returns (index after, code with comments removed and strings blanked).
    When `nested`, stops after the `}` closing a `${` interpolation."""
    stack: List[Tuple[str, int]] = []
    out: List[str] = []
    n = len(src)

    def line(pos: int) -> int:
        return src.count("\n", 0, pos) + 1

    while i < n:
        c = src[i]
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j < 0:
                errors.append(f"line {line(i)}: unterminated block comment")
                return n, "".join(out)
            i = j + 2
            continue
        if c in "'\"":
            triple = src.startswith(c * 3, i)
            term = c * 3 if triple else c
            i = _string(src, i + len(term), term, interpolate=(c == '"'), errors=errors, start=i)
            out.append('""')
            continue
        if c in "([{":
            stack.append((c, i))
        elif c in ")]}":
            if nested and c == "}" and not stack:
                return i + 1, "".join(out)
            if not stack or stack[-1][0] != PAIRS[c]:
                errors.append(f"line {line(i)}: unexpected '{c}'")
            else:
                stack.pop()
        out.append(c)
        i += 1
    for opener, pos in stack:
        errors.append(f"line {line(pos)}: '{opener}' is never closed")
    return n, "".join(out)


def _string(src: str, i: int, term: str, interpolate: bool, errors: List[str], start: int) -> int:
    n = len(src)
    while i < n:
        if src[i] == "\\":
            i += 2
            continue
        if interpolate and src.startswith("${", i):
            i, _ = _scan(src, i + 2, errors, nested=True)
            continue
        if src.startswith(term, i):
            return i + len(term)
        if len(term) == 1 and src[i] == "\n":
            break
        i += 1
    errors.append(f"line {src.count(chr(10), 0, start) + 1}: unterminated string")
    return n


def groovy_code(src: str) -> Tuple[str, List[str]]:
    errors: List[str] = []
    _, code = _scan(src, 0, errors, nested=False)
    return code, errors


def known_step_names() -> Set[str]:
    """Every library step this generator can produce (templates, minus the per-technology CI template)."""
    names = {f[: -len(".groovy.j2")] for f in os.listdir(TEMPLATE_VARS_DIR) if f.endswith(".groovy.j2")}
    names.discard("ciStep")
    return names


def _step_calls(code: str, names: Set[str]) -> Set[str]:
    return {n for n in names if re.search(rf"(?<![\w.]){n}\s*[({{]", code)}


def platform_credentials(bundle: FileBundle) -> Dict[str, str]:
    """key -> credential id, parsed from the generated platformConfig step."""
    text = bundle.files.get(f"{LIB_VARS}platformConfig.groovy", "")
    block = re.search(r"credentials\s*:\s*\[(.*?)\]", text, re.S)
    return dict(re.findall(r"(\w+)\s*:\s*'([^']+)'", block.group(1))) if block else {}


def collect_references(bundle: FileBundle) -> Dict[str, Set[str]]:
    """Jenkins environment variables read via requireEnv, and credential IDs declared in platformConfig."""
    variables: Set[str] = set()
    for path, content in bundle.files.items():
        if path.startswith("shared-library/"):
            variables |= set(REQUIRE_ENV.findall(content))
    return {"vars": variables, "credentials": set(platform_credentials(bundle).values())}


def validate_bundle(bundle: FileBundle) -> List[str]:
    issues: List[str] = []
    generated_steps = {
        p[len(LIB_VARS): -len(".groovy")] for p in bundle.files if p.startswith(LIB_VARS) and p.endswith(".groovy")
    }
    vocabulary = known_step_names() | {s for s in generated_steps if s.startswith("ci")}
    cred_keys = set(platform_credentials(bundle))

    for path, content in sorted(bundle.files.items()):
        if path.endswith((".yml", ".yaml")) and "/templates/" not in path:
            try:
                yaml.safe_load(content)
            except yaml.YAMLError as e:
                issues.append(f"{path}: invalid YAML ({str(e).splitlines()[0]})")
        is_groovy = path.endswith(".groovy") or "/Jenkinsfile." in f"/{path}"
        if not is_groovy:
            continue

        code, errors = groovy_code(content)
        issues += [f"{path}: {e}" for e in errors]
        if re.search(r"<<|<%|<#", code):
            issues.append(f"{path}: unrendered template syntax")
        if HARDCODED_SECRET.search(content):
            issues.append(f"{path}: looks like a hard-coded credential; use Jenkins credentials")
        if DQ_SH_WITH_SECRET.search(content):
            issues.append(f"{path}: sh with a Groovy-interpolated string near a secret; use single quotes and environment variables")
        if re.search(r":latest\b", content):
            issues.append(f"{path}: image pinned to :latest")

        if path.startswith(LIB_VARS):
            issues += _check_library_step(path, content, code, generated_steps, vocabulary, cred_keys)
        elif "/Jenkinsfile." in f"/{path}":
            issues += _check_jenkinsfile(path, content, code, generated_steps, vocabulary)
    return issues


def _check_library_step(path: str, content: str, code: str, generated: Set[str], vocabulary: Set[str],
                        cred_keys: Set[str]) -> List[str]:
    issues: List[str] = []
    own = os.path.basename(path)[: -len(".groovy")]
    if not re.search(r"^\s*(?:\w+(?:<[^>]*>)?)\s+call\s*\(", code, re.M):
        issues.append(f"{path}: library step must define call(...)")
    for step in sorted(_step_calls(code, vocabulary) - {own}):
        if step not in generated:
            issues.append(f"{path}: calls library step '{step}' which was not generated")
    for key in sorted(set(CRED_KEY.findall(content)) - cred_keys):
        if cred_keys:
            issues.append(f"{path}: references credentials.{key} which platformConfig does not define")
    if "pipeline {" in code:
        if re.search(r"agent\s+any\b", code):
            issues.append(f"{path}: 'agent any' - pin pipelines to the configured agent label")
        if "options {" not in code or "timeout(" not in code:
            issues.append(f"{path}: pipeline has no options { '{' } timeout {'}'}")
    return issues


def _check_jenkinsfile(path: str, content: str, code: str, generated: Set[str], vocabulary: Set[str]) -> List[str]:
    issues: List[str] = []
    m = LIBRARY_ANNOTATION.search(content)
    if not m:
        issues.append(f"{path}: missing @Library('<name>@<ref>') _")
    elif m.group(2).lower() in MOVING_REFS:
        issues.append(f"{path}: shared library pinned to moving ref '{m.group(2)}'; use a tag or commit")
    entry = re.findall(r"\b(app(?:Validation|Build|Release)Pipeline)\s*\(", code)
    if len(entry) != 1:
        issues.append(f"{path}: expected exactly one app*Pipeline call, found {len(entry)}")
    for step in sorted(set(entry) | {s for s in re.findall(r"\b(ci[A-Z]\w*)\s*\(", code)}):
        if step not in generated:
            issues.append(f"{path}: calls library step '{step}' which was not generated")
    return issues
