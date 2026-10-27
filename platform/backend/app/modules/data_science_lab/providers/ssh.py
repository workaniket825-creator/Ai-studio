"""SSH provider for static/on-prem GPU targets."""
from __future__ import annotations

import os
import select
import socket
import socketserver
import threading
from dataclasses import dataclass
from typing import Any

from .base import ComputeProvider, ProviderResult


class _ForwardHandler(socketserver.BaseRequestHandler):
    chain_host: str = "127.0.0.1"
    chain_port: int = 0
    transport: Any = None

    def handle(self) -> None:
        try:
            channel = self.transport.open_channel(
                "direct-tcpip",
                (self.chain_host, self.chain_port),
                self.request.getpeername(),
            )
        except Exception:
            return

        if channel is None:
            return

        try:
            while True:
                readable, _, _ = select.select(
                    [self.request, channel], [], [], 30
                )
                if self.request in readable:
                    data = self.request.recv(65536)
                    if not data:
                        break
                    channel.sendall(data)
                if channel in readable:
                    data = channel.recv(65536)
                    if not data:
                        break
                    self.request.sendall(data)
        finally:
            channel.close()
            self.request.close()


class _ThreadingTCPServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


@dataclass
class SSHLocalForward:
    client: Any
    server: _ThreadingTCPServer
    thread: threading.Thread
    local_port: int

    @property
    def is_active(self) -> bool:
        transport = self.client.get_transport()
        return bool(
            self.thread.is_alive()
            and transport
            and transport.is_active()
        )

    def stop(self) -> None:
        try:
            self.server.shutdown()
        finally:
            self.server.server_close()
            self.client.close()
            if self.thread.is_alive():
                self.thread.join(timeout=3)


class SSHProvider(ComputeProvider):
    can_manage_lifecycle = False

    def _client(self):
        import paramiko

        client = paramiko.SSHClient()

        # For immediate compatibility with the current registration flow.
        # Production hardening: mount known_hosts and replace AutoAddPolicy
        # with RejectPolicy after enrolling target fingerprints.
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        return client, paramiko

    def _auth_kwargs(self) -> dict:
        ref = (self.target.get("auth_secret_ref") or "").strip()
        kwargs: dict = {
            "allow_agent": False,
            "look_for_keys": False,
        }
        passphrase = self.target.get("ssh_passphrase") or None

        if ref and os.path.isfile(os.path.expanduser(ref)):
            kwargs["key_filename"] = os.path.expanduser(ref)
            if passphrase:
                kwargs["passphrase"] = passphrase
            return kwargs

        # Retain the repository's legacy agent/~/.ssh fallback when no
        # uploaded file is configured.
        kwargs["allow_agent"] = True
        kwargs["look_for_keys"] = True
        return kwargs

    def _connect(self, client, timeout: int = 10) -> None:
        client.connect(
            hostname=self.target["host"],
            port=int(self.target.get("ssh_port", 22)),
            username=self.target.get("ssh_user", "ubuntu"),
            timeout=timeout,
            banner_timeout=timeout,
            auth_timeout=timeout,
            **self._auth_kwargs(),
        )
        transport = client.get_transport()
        if transport is None or not transport.is_active():
            raise RuntimeError("SSH transport is not active")
        transport.set_keepalive(30)

    def test_connection(self) -> ProviderResult:
        host = self.target.get("host")
        port = int(self.target.get("ssh_port", 22))
        if not host:
            return ProviderResult(
                ok=False, status="unreachable", detail="host is required"
            )

        try:
            with socket.create_connection((host, port), timeout=6):
                pass
        except Exception as exc:
            return ProviderResult(
                ok=False,
                status="unreachable",
                detail=f"cannot reach {host}:{port}: {exc}",
            )

        ref = (self.target.get("auth_secret_ref") or "").strip()
        if (
            ref
            and not os.path.isfile(os.path.expanduser(ref))
            and not ref.startswith("vault://")
        ):
            return ProviderResult(
                ok=False,
                status="unreachable",
                detail="auth_secret_ref is not a readable backend key file",
            )

        client = None
        try:
            client, _ = self._client()
            self._connect(client, timeout=8)
            return ProviderResult(
                ok=True,
                status="idle",
                detail=f"SSH auth OK to {host}:{port}",
            )
        except Exception as exc:
            return ProviderResult(
                ok=False,
                status="unreachable",
                detail=f"reachable but SSH auth failed: {exc}",
            )
        finally:
            if client is not None:
                client.close()

    def exec(self, cmd: str) -> ProviderResult:
        client = None
        try:
            client, _ = self._client()
            self._connect(client, timeout=12)
            _, stdout, stderr = client.exec_command(cmd, timeout=180)
            output = stdout.read().decode("utf-8", errors="replace")[:8000]
            error = stderr.read().decode("utf-8", errors="replace")[:2000]
            exit_code = stdout.channel.recv_exit_status()
            return ProviderResult(
                ok=exit_code == 0,
                stdout=output,
                stderr=error,
                exit_code=exit_code,
                detail=error.strip() if exit_code else "",
            )
        except Exception as exc:
            return ProviderResult(ok=False, detail=str(exc))
        finally:
            if client is not None:
                client.close()

    def tunnel(self, local: int, remote: int) -> ProviderResult:
        """Create a real backend-local forward to target loopback."""
        client = None
        server = None
        try:
            client, _ = self._client()
            self._connect(client, timeout=12)
            transport = client.get_transport()

            handler = type(
                "DSLabForwardHandler",
                (_ForwardHandler,),
                {
                    "chain_host": "127.0.0.1",
                    "chain_port": int(remote),
                    "transport": transport,
                },
            )
            # Bind on all interfaces (not just loopback) so a sibling container — the jupyter-mcp
            # service — can reach this DSLab tunnel at http://backend:<port>. The chain_host above
            # stays 127.0.0.1 (that's the TARGET side, inside the SSH host).
            server = _ThreadingTCPServer(
                ("0.0.0.0", int(local)), handler
            )
            local_port = int(server.server_address[1])
            thread = threading.Thread(
                target=server.serve_forever,
                name=f"dslab-ssh-{local_port}",
                daemon=True,
            )
            thread.start()

            forward = SSHLocalForward(
                client=client,
                server=server,
                thread=thread,
                local_port=local_port,
            )
            if not forward.is_active:
                forward.stop()
                raise RuntimeError("SSH tunnel did not become active")

            return ProviderResult(
                ok=True,
                local_port=local_port,
                remote_port=int(remote),
                forwarder=forward,
                detail=(
                    f"backend 127.0.0.1:{local_port} -> "
                    f"target 127.0.0.1:{remote}"
                ),
            )
        except Exception as exc:
            if server is not None:
                try:
                    server.server_close()
                except Exception:
                    pass
            if client is not None:
                client.close()
            return ProviderResult(
                ok=False, detail=f"SSH tunnel failed: {exc}"
            )
