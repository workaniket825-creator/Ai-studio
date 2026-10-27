"""AWS + Azure managed providers — real lifecycle (spec §6.1, §14 Phase 2).

Both implement start()/stop() against the provider SDK (boto3 / azure-mgmt-compute).
Calls are real but guarded: if the SDK isn't installed or credentials aren't resolvable
from the secret store, they return an honest status instead of failing hard. Once an
instance is running, exec()/tunnel() go over SSH like every other target (§3 invariant).

Instance identity:
- AWS:   target.host holds the EC2 instance-id (i-...), target.region the region.
- Azure: target.host holds "<resource_group>/<vm_name>".
"""
from __future__ import annotations

from .base import ComputeProvider, ProviderResult
from .ssh import SSHProvider


class _ManagedBase(ComputeProvider):
    can_manage_lifecycle = True
    _name = "managed"

    def exec(self, cmd: str) -> ProviderResult:
        return SSHProvider(self.target).exec(cmd)

    def tunnel(self, local: int, remote: int) -> ProviderResult:
        return SSHProvider(self.target).tunnel(local, remote)


class AWSProvider(_ManagedBase):
    _name = "AWS"

    def _client(self):
        import boto3
        region = self.target.get("region") or "us-east-1"
        return boto3.client("ec2", region_name=region)

    def test_connection(self) -> ProviderResult:
        iid = self.target.get("host")
        if not iid:
            return ProviderResult(ok=False, status="not_configured",
                                  detail="set host to the EC2 instance-id (i-...)")
        try:
            ec2 = self._client()
        except Exception:
            return ProviderResult(ok=False, status="not_configured",
                                  detail="boto3 not installed / AWS creds unavailable on the control plane")
        try:
            r = ec2.describe_instances(InstanceIds=[iid])
            state = r["Reservations"][0]["Instances"][0]["State"]["Name"]
            return ProviderResult(ok=True, status="running" if state == "running" else "idle",
                                  detail=f"EC2 {iid} state={state}")
        except Exception as e:
            return ProviderResult(ok=False, status="unreachable", detail=f"describe failed: {e}")

    def start(self) -> ProviderResult:
        try:
            self._client().start_instances(InstanceIds=[self.target["host"]])
            return ProviderResult(ok=True, status="running", detail="EC2 start requested")
        except Exception as e:
            return ProviderResult(ok=False, detail=f"AWS start failed: {e} (install boto3 + credentials)")

    def stop(self) -> ProviderResult:
        try:
            self._client().stop_instances(InstanceIds=[self.target["host"]])
            return ProviderResult(ok=True, status="idle", detail="EC2 stop requested")
        except Exception as e:
            return ProviderResult(ok=False, detail=f"AWS stop failed: {e}")


class AzureProvider(_ManagedBase):
    _name = "Azure"

    def _parts(self):
        host = self.target.get("host", "")
        if "/" not in host:
            raise ValueError("set host to '<resource_group>/<vm_name>'")
        rg, vm = host.split("/", 1)
        return rg, vm

    def _client(self):
        import os
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.compute import ComputeManagementClient
        return ComputeManagementClient(DefaultAzureCredential(), os.getenv("AZURE_SUBSCRIPTION_ID", ""))

    def test_connection(self) -> ProviderResult:
        try:
            rg, vm = self._parts()
        except ValueError as e:
            return ProviderResult(ok=False, status="not_configured", detail=str(e))
        try:
            c = self._client()
        except Exception:
            return ProviderResult(ok=False, status="not_configured",
                                  detail="azure-mgmt-compute not installed / Azure creds unavailable")
        try:
            iv = c.virtual_machines.instance_view(rg, vm)
            statuses = [s.code for s in (iv.statuses or [])]
            running = any("running" in s for s in statuses)
            return ProviderResult(ok=True, status="running" if running else "idle",
                                  detail=f"Azure VM {vm} statuses={statuses}")
        except Exception as e:
            return ProviderResult(ok=False, status="unreachable", detail=f"instance_view failed: {e}")

    def start(self) -> ProviderResult:
        try:
            rg, vm = self._parts()
            self._client().virtual_machines.begin_start(rg, vm)
            return ProviderResult(ok=True, status="running", detail="Azure VM start requested")
        except Exception as e:
            return ProviderResult(ok=False, detail=f"Azure start failed: {e} (install azure-mgmt-compute + credentials)")

    def stop(self) -> ProviderResult:
        try:
            rg, vm = self._parts()
            self._client().virtual_machines.begin_deallocate(rg, vm)
            return ProviderResult(ok=True, status="idle", detail="Azure VM deallocate requested")
        except Exception as e:
            return ProviderResult(ok=False, detail=f"Azure stop failed: {e}")
