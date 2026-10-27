"""Data Science Lab — self-contained, non-invasive module (spec §1).

Everything is under this package + one router + one UI route tree. The platform is a
dependency this module consumes (MLflow, governance settings, secret references),
never something it edits. Ships dark behind a feature flag.
"""
from .config import is_enabled, get_config

__all__ = ["is_enabled", "get_config"]
