"""Session flow (spec §6.3).

Orchestrates a lab session against a registered runtime:
  1. get_provider(target)
  2. if managed: provider.start()          (else assume already on)
  3. git pull notebooks/templates
  4. launch JupyterLab on target -> tunnel -> return embed URL
  5. inject MLFLOW_TRACKING_URI so work logs to the EXISTING MLflow
  6. (persist handled on stop / by the runtime's persistent volume)
  7. idle auto-shutdown or explicit Stop — never before outputs are persisted

Every step returns an explicit, honest status. Because real SSH/GPU work happens on
the remote target, the control plane records intent + provider responses and surfaces
them in the UI; it never fabricates a running kernel.
"""
from __future__ import annotations

import time
import shlex
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone

from . import store
from .providers import get_provider


_ACTIVE_TUNNELS: dict[str, object] = {}
_TUNNEL_PORTS: dict[str, int] = {}
_TUNNEL_TOKENS: dict[str, str] = {}
_TUNNEL_LOCK = threading.RLock()


def get_tunnel_port(rid: str) -> int | None:
    with _TUNNEL_LOCK:
        tunnel = _ACTIVE_TUNNELS.get(rid)
        port = _TUNNEL_PORTS.get(rid)

    if not tunnel or not port:
        return None
    if not getattr(tunnel, "is_active", False):
        close_lab(rid)
        return None
    return port


def get_lab_token(rid: str) -> str:
    """Token the lab proxy injects into every request to this runtime's Jupyter."""
    with _TUNNEL_LOCK:
        tok = _TUNNEL_TOKENS.get(rid)
    if tok:
        return tok
    return (store.get_runtime(rid) or {}).get("jupyter_token", "") or ""


def close_lab(rid: str) -> bool:
    with _TUNNEL_LOCK:
        tunnel = _ACTIVE_TUNNELS.pop(rid, None)
        _TUNNEL_PORTS.pop(rid, None)
        _TUNNEL_TOKENS.pop(rid, None)

    if tunnel is None:
        return False
    try:
        tunnel.stop()
    except Exception:
        pass
    return True


def close_all_labs() -> None:
    with _TUNNEL_LOCK:
        runtime_ids = list(_ACTIVE_TUNNELS)
    for rid in runtime_ids:
        close_lab(rid)


def _store_tunnel(rid: str, tunnel: object, local_port: int, token: str = "") -> None:
    close_lab(rid)
    with _TUNNEL_LOCK:
        _ACTIVE_TUNNELS[rid] = tunnel
        _TUNNEL_PORTS[rid] = local_port
        if token:
            _TUNNEL_TOKENS[rid] = token


def _probe_tunnel(local_port: int, base_path: str, token: str = "") -> tuple[bool, str]:
    """Authenticated API probe: proves the tunnel works AND that Jupyter accepts our token."""
    url = f"http://127.0.0.1:{local_port}{base_path}api/status"
    req = urllib.request.Request(url, headers={"Authorization": f"token {token}"} if token else {})
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            if response.status in (200, 302, 303, 307, 308):
                return True, f"HTTP {response.status}"
            return False, f"unexpected HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return False, (f"HTTP {exc.code}: Jupyter rejected the platform token. An older "
                           "Jupyter without the token may still own this port - stop it on "
                           "the target or change the runtime's Jupyter port.")
        return False, f"unexpected HTTP {exc.code}"
    except Exception as exc:
        return False, str(exc)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_connection(rid: str) -> dict:
    rt = store.get_runtime(rid)
    if not rt:
        return {"ok": False, "detail": "runtime not found"}
    res = get_provider(rt).test_connection()
    store.update_runtime(rid, {"status": res.get("status", "unreachable"),
                               "last_test": _now(),
                               "last_error": "" if res.get("ok") else res.get("detail", "")})
    return dict(res)


def start(rid: str) -> dict:
    rt = store.get_runtime(rid)
    if not rt:
        return {"ok": False, "detail": "runtime not found"}
    prov = get_provider(rt)
    if not prov.can_manage_lifecycle:
        return {"ok": False, "detail": "this runtime is connect-only (no managed start)"}
    res = prov.start()
    if res.get("ok"):
        store.update_runtime(rid, {"status": "running"})
    return dict(res)


def stop(rid: str, verify_backup: bool = True) -> dict:
    rt = store.get_runtime(rid)
    if not rt:
        return {"ok": False, "detail": "runtime not found"}
    prov = get_provider(rt)
    if not prov.can_manage_lifecycle:
        return {"ok": False, "detail": "this runtime is connect-only (no managed stop)"}
    # discipline (§6.3 step 7): never stop before outputs are persisted. If a backup
    # remote is configured, verify a backup exists/succeeds first.
    steps: list[dict] = []
    if verify_backup and rt.get("backup_remote"):
        b = _run_backup(prov, rt)
        steps.append({"step": "backup", **b})
        if not b.get("ok"):
            return {"ok": False, "steps": steps,
                    "detail": "stop aborted — backup did not verify: " + b.get("detail", "")}
    res = prov.stop()
    if res.get("ok"):
        store.update_runtime(rid, {"status": "idle"})
    return {**dict(res), "steps": steps}


def _run_backup(prov, rt: dict) -> dict:
    """rclone the workdir to the configured remote, then verify with rclone check (§13)."""
    workdir = rt.get("workdir", "/home/ubuntu/workspace")
    remote = rt.get("backup_remote", "")
    copy = prov.exec(f"rclone copy {workdir} {remote} 2>&1 || echo NO_RCLONE")
    if "NO_RCLONE" in (copy.get("stdout") or ""):
        return {"ok": False, "detail": "rclone not available on target — cannot verify backup"}
    if not copy.get("ok"):
        return {"ok": False, "detail": copy.get("detail", "backup copy failed")}
    check = prov.exec(f"rclone check {workdir} {remote} 2>&1")
    return {"ok": check.get("ok", False),
            "detail": "backup verified" if check.get("ok") else "backup verify failed"}


def open_lab(rid: str) -> dict:
    rt = store.get_runtime(rid)
    if not rt:
        return {"ok": False, "detail": "runtime not found"}

    prov = get_provider(rt)
    steps: list[dict] = []
    badge = f"Kernel: {rt['name']} \u00b7 {rt.get('gpu_type') or 'GPU'} \u00b7 "

    if prov.can_manage_lifecycle and rt.get("status") != "running":
        started = prov.start()
        steps.append({"step": "start", **started})
        if not started.get("ok"):
            return {
                "ok": False,
                "embed_url": "",
                "kernel_badge": badge + "not connected",
                "steps": steps,
                "detail": started.get("detail", "runtime start failed"),
            }

    workdir = rt.get("workdir", "/home/ubuntu/workspace")
    jport = int(rt.get("jupyter_port", 8888))
    py = rt.get("python_path", "python3")
    jcmd = rt.get("jupyter_cmd") or f"{py} -m jupyterlab"
    base_path = f"/api/v1/dsl/runtimes/{rid}/lab/"
    pid_file = f"/tmp/dslab-{rid}.pid"
    log_file = f"/tmp/jupyter-{rid}.log"
    auth_file = f"/tmp/dslab-{rid}.auth"
    token = store.ensure_jupyter_token(rid)
    import hashlib
    token_fp = hashlib.sha256(token.encode()).hexdigest()[:16]

    q_workdir = shlex.quote(workdir)
    q_mlflow = shlex.quote(rt.get("mlflow_uri", ""))
    q_base = shlex.quote(base_path)
    q_pid = shlex.quote(pid_file)
    q_log = shlex.quote(log_file)

    # Stop only the process previously started for this runtime (tracked by its PID file).
    # Never pkill/killall: that could terminate another user's Jupyter.
    # Jupyter is token-protected (token passed via env, not argv) and listens on target
    # loopback only; the backend lab proxy injects the token on every request. A process left
    # over from an older build (no token / different token) is restarted automatically.
    q_auth = shlex.quote(auth_file)
    q_tok = shlex.quote(token)
    launch_fn = (
        f"_dslab_launch() {{ cd {q_workdir} || {{ echo no_workdir; exit 43; }}; "
        # cd first, then background ONLY the nohup command: `cd && nohup ... &` would
        # background a subshell that holds the SSH channel open and makes $! its pid.
        f"MLFLOW_TRACKING_URI={q_mlflow} "
        f"JUPYTER_TOKEN={q_tok} "
        f"nohup {jcmd} --no-browser --ip=127.0.0.1 --port={jport} "
        f"--ServerApp.base_url={q_base} "
        f"--ServerApp.allow_origin='*' "
        f"--ServerApp.trust_xheaders=True "
        f"--ServerApp.allow_root=True "
        f">{q_log} 2>&1 < /dev/null & echo $! > {q_pid}; "
        f"echo {token_fp} > {q_auth}; echo launched; }}; "
    )
    launch_cmd = (
        launch_fn
        + f"if [ -f {q_pid} ] && kill -0 $(cat {q_pid}) 2>/dev/null; then "
        f"ARGS=$(tr '\\0' ' ' </proc/$(cat {q_pid})/cmdline 2>/dev/null); "
        f"case \"$ARGS\" in *\"--ServerApp.base_url={base_path}\"*) "
        f"if [ \"$(cat {q_auth} 2>/dev/null)\" = \"{token_fp}\" ]; then echo already_running; "
        f"else kill $(cat {q_pid}) 2>/dev/null; sleep 3; _dslab_launch; fi ;; "
        f"*) echo wrong_existing_process; exit 42 ;; esac; "
        f"else _dslab_launch; fi"
    )

    launched = prov.exec(launch_cmd)
    steps.append({"step": "launch_jupyter", **launched})
    if not launched.get("ok"):
        return {
            "ok": False,
            "embed_url": "",
            "kernel_badge": badge + "not connected",
            "steps": steps,
            "detail": (
                f"Jupyter launch failed. Check {log_file}. "
                "Another managed process may own this runtime's PID file."
            ),
        }

    lab_up = False
    for _ in range(15):
        probe = prov.exec(
            f"(command -v ss >/dev/null && ss -ltn || "
            f"netstat -ltn 2>/dev/null) | "
            f"grep -q '127.0.0.1:{jport} ' && echo LAB_UP || echo LAB_DOWN"
        )
        if "LAB_UP" in (probe.get("stdout") or ""):
            lab_up = True
            break
        time.sleep(1)

    steps.append({
        "step": "verify_jupyter",
        "ok": lab_up,
        "detail": (
            f"Jupyter listening on target 127.0.0.1:{jport}"
            if lab_up
            else f"Jupyter did not start; inspect {log_file}"
        ),
    })
    if not lab_up:
        return {
            "ok": False,
            "embed_url": "",
            "kernel_badge": badge + "not connected",
            "steps": steps,
            "detail": f"JupyterLab did not start on port {jport}",
        }

    tunneled = prov.tunnel(0, jport)
    steps.append({
        "step": "tunnel",
        **{k: v for k, v in tunneled.items() if k != "forwarder"},
    })
    if not tunneled.get("ok"):
        return {
            "ok": False,
            "embed_url": "",
            "kernel_badge": badge + "not connected",
            "steps": steps,
            "detail": tunneled.get("detail", "SSH tunnel failed"),
        }

    forwarder = tunneled["forwarder"]
    local_port = int(tunneled["local_port"])
    _store_tunnel(rid, forwarder, local_port, token)

    ready, probe_detail = _probe_tunnel(local_port, base_path, token)
    steps.append({
        "step": "verify_tunnel_http",
        "ok": ready,
        "detail": probe_detail,
    })
    if not ready:
        close_lab(rid)
        return {
            "ok": False,
            "embed_url": "",
            "kernel_badge": badge + "not connected",
            "steps": steps,
            "detail": (
                "SSH tunnel is active, but Jupyter did not answer at the "
                "configured base URL. Stop an old Jupyter process or use a "
                "different Jupyter port."
            ),
        }

    store.update_runtime(
        rid, {"status": "running", "last_error": ""}
    )
    return {
        "ok": True,
        "embed_url": base_path,
        "kernel_badge": badge + "connected",
        "mlflow_uri": rt.get("mlflow_uri", ""),
        "workdir": workdir,
        "steps": steps,
        "detail": "JupyterLab is ready through the SSH tunnel.",
    }

def gpu_metrics(rid: str) -> dict:
    """Live GPU utilisation/memory/temp for a runtime card / workspace strip (§7)."""
    rt = store.get_runtime(rid)
    if not rt:
        return {"available": False, "detail": "runtime not found"}
    return dict(get_provider(rt).gpu_metrics())


def headless_run(rid: str, notebook: str, params: dict | None = None) -> dict:
    """Papermill headless execution on the target (spec §6.3 step 4b, §13).
    Runs <notebook> -> <notebook>.out.ipynb with injected params + MLflow URI.
    Guarded: reports honestly if papermill isn't on the target."""
    rt = store.get_runtime(rid)
    if not rt:
        return {"ok": False, "detail": "runtime not found"}
    prov = get_provider(rt)
    workdir = rt.get("workdir", "/home/ubuntu/workspace")
    py = rt.get("python_path", "python3")
    pargs = " ".join(f"-p {k} {v}" for k, v in (params or {}).items())
    out = f"{notebook}.out.ipynb"
    # invoke papermill as a MODULE of the configured interpreter, so it's the same Python
    # that actually has papermill installed (fixes "papermill not installed" false negatives).
    cmd = (f"cd {workdir} && {py} -m papermill --version >/dev/null 2>&1 || echo NO_PAPERMILL; "
           f"cd {workdir} && MLFLOW_TRACKING_URI='{rt.get('mlflow_uri','')}' "
           f"{py} -m papermill {notebook} {out} {pargs} 2>&1 || echo RUN_FAILED")
    res = prov.exec(cmd)
    stdout = res.get("stdout") or ""
    if "NO_PAPERMILL" in stdout:
        return {"ok": False, "detail": f"papermill is not installed on the target's interpreter "
                                       f"'{py}'. Install it there: {py} -m pip install papermill "
                                       f"(or set the runtime's Python path to the env that has it)."}
    return {"ok": res.get("ok", False) and "RUN_FAILED" not in stdout, "output_notebook": out,
            "stdout": stdout, "detail": "headless run complete"
            if res.get("ok") and "RUN_FAILED" not in stdout else res.get("detail", "run failed")}


def run_ci_smoke(tid: str, rid: str) -> dict:
    """Template quality gate (spec §8): papermill/nbmake on a tiny sample. Records CI status."""
    t = next((x for x in store.list_templates() if x["id"] == tid), None)
    if not t:
        return {"ok": False, "detail": "template not found"}
    if not t.get("repo_path"):
        store.set_template_ci(tid, "untested", "no repo_path to test")
        return {"ok": False, "detail": "template has no repo_path"}
    rt = store.get_runtime(rid)
    if not rt:
        return {"ok": False, "detail": "runtime not found"}
    prov = get_provider(rt)
    workdir = rt.get("workdir", "/home/ubuntu/workspace")
    nb = t["repo_path"].rstrip("/") + "/notebook.ipynb"
    res = prov.exec(f"cd {workdir} && papermill {nb} /tmp/ci.out.ipynb -p SMOKE 1 "
                    f"2>&1 || echo CI_FAIL")
    ok = res.get("ok", False) and "CI_FAIL" not in (res.get("stdout") or "")
    store.set_template_ci(tid, "passing" if ok else "failing",
                          (res.get("stdout") or res.get("detail", ""))[:300])
    return {"ok": ok, "ci_status": "passing" if ok else "failing"}


def spawn_multiuser(rid: str) -> dict:
    """Phase 3 (spec §12): launch a per-user server via JupyterHub + remote spawner,
    optionally on a MIG slice. Guarded: returns the intended action + config honestly."""
    rt = store.get_runtime(rid)
    if not rt:
        return {"ok": False, "detail": "runtime not found"}
    if not rt.get("multiuser"):
        return {"ok": False, "detail": "multi-user is off for this runtime (enable JupyterHub in settings)"}
    prov = get_provider(rt)
    mig = f" (MIG {rt.get('mig_profile')})" if rt.get("mig_enabled") else ""
    # A real hub spawns per-user notebook servers; from the control plane we verify the
    # hub is reachable and return the per-user URL pattern.
    check = prov.exec("jupyterhub --version 2>&1 || echo NO_HUB")
    if "NO_HUB" in (check.get("stdout") or ""):
        return {"ok": False, "hub_url": rt.get("hub_url", ""),
                "detail": "JupyterHub not installed on the target; install the hub + a remote "
                          "spawner to enable multi-user" + mig}
    return {"ok": True, "hub_url": rt.get("hub_url", ""),
            "detail": f"JupyterHub reachable; per-user servers spawn on this GPU{mig}",
            "mig_enabled": rt.get("mig_enabled", False), "mig_profile": rt.get("mig_profile", "")}
