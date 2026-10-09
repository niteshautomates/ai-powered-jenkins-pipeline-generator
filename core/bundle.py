# core/bundle.py
"""In-memory set of generated files, written to disk once at the end."""

import os
from typing import Dict


class FileBundle:
    def __init__(self) -> None:
        self.files: Dict[str, str] = {}

    def add(self, path: str, content: str) -> None:
        # Shared files (composite actions, reusable workflows) may be rendered once per app;
        # identical content is fine, differing content is a bug in a template or tool.
        if path in self.files and self.files[path] != content:
            raise ValueError(f"Conflicting content generated for {path}")
        self.files[path] = content

    def write(self, out_dir: str) -> None:
        for path, content in self.files.items():
            dest = os.path.join(out_dir, path)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w") as f:
                f.write(content)
