# config/__init__.py

from .settings import Settings, settings
from .technology_config import TECH_CONFIG, load_tech_config

__all__ = ["Settings", "settings", "TECH_CONFIG", "load_tech_config"]
