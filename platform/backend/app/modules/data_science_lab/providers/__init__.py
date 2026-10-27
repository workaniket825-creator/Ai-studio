"""Provider registry + factory (spec §6.1). New backend later = one new class."""
from __future__ import annotations

from .base import ComputeProvider
from .ssh import SSHProvider
from .brev import BrevProvider
from .managed import AWSProvider, AzureProvider

PROVIDERS = {
    "ssh": SSHProvider,      # connect only — on-prem / static NVIDIA hosts
    "brev": BrevProvider,    # connect + lifecycle (NVIDIA-owned) — default managed
    "aws": AWSProvider,      # connect + lifecycle (Phase 2)
    "azure": AzureProvider,  # connect + lifecycle (Phase 2)
}


def get_provider(target: dict) -> ComputeProvider:
    cls = PROVIDERS.get(target.get("provider", "ssh"), SSHProvider)
    return cls(target)
