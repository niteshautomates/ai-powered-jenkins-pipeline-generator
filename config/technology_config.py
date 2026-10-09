# config/technology_config.py

import os
from functools import lru_cache
from typing import Any, Dict

import yaml


@lru_cache(maxsize=1)
def load_tech_config() -> Dict[str, Any]:
    """Load technology configuration from YAML (cached)."""
    path = os.path.join(os.path.dirname(__file__), "technology_config.yaml")
    with open(path, "r") as f:
        return yaml.safe_load(f)


TECH_CONFIG = load_tech_config()
