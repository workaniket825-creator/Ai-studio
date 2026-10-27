"""Provider adapter pattern (spec §6.1).

Every target is reached over SSH (portability invariant, §3). Managed providers add
a start/stop lifecycle on top. Real SSH/provider calls are written and wired but
guarded: without the optional dependency (paramiko / provider SDK) or a reachable
target they return an honest, explicit result instead of faking success — so the
control plane never depends on GPU-side availability.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class ProviderResult(dict):
    """Small typed-ish result: {ok, detail, ...}."""


class ComputeProvider(ABC):
    can_manage_lifecycle = False

    def __init__(self, target: dict):
        self.target = target

    @abstractmethod
    def test_connection(self) -> ProviderResult:
        """Probe BOTH auth and reachability (spec §11.4)."""

    @abstractmethod
    def exec(self, cmd: str) -> ProviderResult:
        """Run a command on the target over SSH."""

    @abstractmethod
    def tunnel(self, local: int, remote: int) -> ProviderResult:
        """Forward a port (for JupyterLab)."""

    def start(self) -> ProviderResult:
        return ProviderResult(ok=False, detail="this provider cannot start/stop runtimes")

    def stop(self) -> ProviderResult:
        return ProviderResult(ok=False, detail="this provider cannot start/stop runtimes")

    def gpu_metrics(self) -> ProviderResult:
        """GPU utilisation/memory/temp via nvidia-smi on the target (spec §7).
        Guarded: returns available=False with an honest reason if not obtainable."""
        res = self.exec(
            "nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu "
            "--format=csv,noheader,nounits 2>/dev/null || echo NO_SMI")
        if not res.get("ok"):
            return ProviderResult(available=False, detail=res.get("detail", "exec failed"))
        out = (res.get("stdout") or "").strip()
        if not out or "NO_SMI" in out:
            return ProviderResult(available=False,
                                  detail="nvidia-smi not available on the target (no GPU or driver)")
        gpus = []
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) == 4:
                try:
                    gpus.append({"util_pct": float(parts[0]), "mem_used_mb": float(parts[1]),
                                 "mem_total_mb": float(parts[2]), "temp_c": float(parts[3])})
                except ValueError:
                    continue
        return ProviderResult(available=bool(gpus), gpus=gpus)

    # shared helper: resolve a secret *reference* from the platform's secret store
    def _resolve_secret(self) -> str | None:
        ref = self.target.get("auth_secret_ref", "")
        if not ref:
            return None
        # In this platform secrets are stored by reference; a real deployment resolves
        # vault://... here. We never persist raw secrets (spec §11).
        return ref
