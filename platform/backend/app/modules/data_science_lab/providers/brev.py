"""BrevProvider — managed connect + lifecycle (spec §6.1).

Brev is NVIDIA-owned and the sensible default managed provider (§7). Uses the `brev`
CLI when present; otherwise reports honestly. Managed => can start/stop and enforce
idle auto-shutdown.
"""
from __future__ import annotations

import shutil
import subprocess

from .base import ComputeProvider, ProviderResult
from .ssh import SSHProvider


class BrevProvider(ComputeProvider):
    can_manage_lifecycle = True

    def _cli(self) -> str | None:
        return shutil.which("brev")

    def _run(self, *args) -> ProviderResult:
        cli = self._cli()
        if not cli:
            return ProviderResult(ok=False, detail="brev CLI not installed on the control plane "
                                                    "(pip/npm install the brev CLI to manage lifecycle)")
        try:
            p = subprocess.run([cli, *args], capture_output=True, text=True, timeout=60)
            return ProviderResult(ok=p.returncode == 0, stdout=p.stdout[:4000],
                                  stderr=p.stderr[:2000], detail=p.stderr[:200] if p.returncode else "")
        except Exception as e:
            return ProviderResult(ok=False, detail=str(e))

    def test_connection(self) -> ProviderResult:
        cli = self._cli()
        if not cli:
            return ProviderResult(ok=False, status="not_configured",
                                  detail="brev CLI not installed on the control plane. "
                                         "Once installed + authenticated, Test verifies the instance.")
        r = self._run("ls")
        if not r["ok"]:
            return ProviderResult(ok=False, status="unreachable", detail=r.get("detail") or "brev ls failed")
        name = self.target.get("host") or self.target.get("name", "")
        present = name and name in (r.get("stdout") or "")
        return ProviderResult(ok=True, status="idle" if present else "not_configured",
                              detail=f"brev reachable; instance '{name}' "
                                     + ("found" if present else "not found in account"))

    def start(self) -> ProviderResult:
        name = self.target.get("host") or self.target.get("name")
        r = self._run("start", name)
        r["status"] = "running" if r["ok"] else "unreachable"
        return r

    def stop(self) -> ProviderResult:
        name = self.target.get("host") or self.target.get("name")
        r = self._run("stop", name)
        r["status"] = "idle" if r["ok"] else "running"
        return r

    # once started, exec/tunnel go over SSH just like any other target (§3 invariant)
    def exec(self, cmd: str) -> ProviderResult:
        return SSHProvider(self.target).exec(cmd)

    def tunnel(self, local: int, remote: int) -> ProviderResult:
        return SSHProvider(self.target).tunnel(local, remote)
