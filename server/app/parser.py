import io
import os
import re
import tarfile
import uuid
from datetime import datetime, timezone
from typing import Dict, Tuple

ERROR_RE = re.compile(r"\b(error|failed|fail|panic|critical|segfault)\b", re.IGNORECASE)

def _safe_members(t: tarfile.TarFile):
    # prevent path traversal
    for m in t.getmembers():
        p = m.name
        if p.startswith("/") or ".." in p.split("/"):
            continue
        if m.islnk() or m.issym():
            continue
        yield m

def _read_text(t: tarfile.TarFile, name_endswith: str) -> str:
    # Find a member ending with name_endswith (since top folder includes host-timestamp)
    member = next((m for m in t.getmembers() if m.name.endswith("/" + name_endswith) or m.name.endswith(name_endswith)), None)
    if not member:
        return ""
    f = t.extractfile(member)
    if not f:
        return ""
    data = f.read()
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return data.decode(errors="replace")

def parse_run(archive_bytes: bytes, archive_name: str) -> Tuple[dict, Dict[str, float], Dict[str, str]]:
    """
    Returns: run_info, metrics, artifacts
    - run_info: id, created_at, host, archive_name, uname, os_release
    - metrics: numeric values
    - artifacts: raw text blobs (for UI)
    """
    run_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as t:
        # Validate members quickly (safe)
        _ = list(_safe_members(t))

        meta = _read_text(t, "meta.txt")
        uname = _read_text(t, "uname.txt")
        os_release = _read_text(t, "os_release.txt")
        df_txt = _read_text(t, "df.txt")
        free_txt = _read_text(t, "free.txt")
        log_tail = _read_text(t, "log_tail.txt")
        running_services = _read_text(t, "systemd_running_services.txt")
        failed_units = _read_text(t, "systemd_failed_units.txt")
        k8s_nodes = _read_text(t, "k8s_nodes.txt")
        k8s_pods = _read_text(t, "k8s_pods.txt")

    host = "unknown"
    for line in meta.splitlines():
        if line.startswith("host="):
            host = line.split("=", 1)[1].strip() or "unknown"

    metrics: Dict[str, float] = {}

    # Parse memory from `free -b` (line starts with Mem:)
    mem_total = mem_used = None
    for line in free_txt.splitlines():
        if line.strip().startswith("Mem:"):
            parts = line.split()
            # Mem: total used free shared buff/cache available
            if len(parts) >= 3:
                mem_total = float(parts[1])
                mem_used = float(parts[2])
            break
    if mem_total and mem_used is not None and mem_total > 0:
        metrics["mem_used_pct"] = round((mem_used / mem_total) * 100.0, 2)
        metrics["mem_used_bytes"] = mem_used
        metrics["mem_total_bytes"] = mem_total

    # Parse disk root usage from df -P
    # Look for mount point "/"
    root_use = None
    for line in df_txt.splitlines():
        if not line.strip() or line.lower().startswith("filesystem"):
            continue
        parts = line.split()
        if len(parts) >= 7 and parts[-1] == "/":
            # ... Use% is typically parts[-2]
            usep = parts[-2].strip()
            if usep.endswith("%"):
                try:
                    root_use = float(usep[:-1])
                except ValueError:
                    pass
            break
    if root_use is not None:
        metrics["disk_root_used_pct"] = root_use

    # systemd running services count (rough)
    run_count = 0
    for line in running_services.splitlines():
        if line.strip().endswith(".service") and "loaded" in line:
            run_count += 1
    metrics["systemd_running_services"] = float(run_count)

    # failed units count (rough)
    failed_count = 0
    for line in failed_units.splitlines():
        if ".service" in line and "failed" in line:
            failed_count += 1
    metrics["systemd_failed_units"] = float(failed_count)

    # log error signals count
    err_count = sum(1 for line in log_tail.splitlines() if ERROR_RE.search(line))
    metrics["log_error_signals_200lines"] = float(err_count)

    # k8s nodes/pods counts
    # `kubectl get nodes` has header NAME STATUS ROLES AGE VERSION ...
    if k8s_nodes and "kubectl not found" not in k8s_nodes.lower():
        lines = [ln for ln in k8s_nodes.splitlines() if ln.strip()]
        if len(lines) > 1:
            metrics["k8s_nodes_total"] = float(len(lines) - 1)
            not_ready = 0
            for ln in lines[1:]:
                cols = ln.split()
                if len(cols) >= 2 and "Ready" not in cols[1]:
                    not_ready += 1
            metrics["k8s_nodes_not_ready"] = float(not_ready)

    if k8s_pods and "kubectl not found" not in k8s_pods.lower():
        lines = [ln for ln in k8s_pods.splitlines() if ln.strip()]
        if len(lines) > 1:
            metrics["k8s_pods_total"] = float(len(lines) - 1)

    # Health score (simple but compelling)
    score = 100.0
    disk = metrics.get("disk_root_used_pct", 0.0)
    mem = metrics.get("mem_used_pct", 0.0)
    errs = metrics.get("log_error_signals_200lines", 0.0)
    not_ready = metrics.get("k8s_nodes_not_ready", 0.0)
    failed = metrics.get("systemd_failed_units", 0.0)

    if disk >= 90: score -= 25
    elif disk >= 80: score -= 15
    elif disk >= 70: score -= 8

    if mem >= 90: score -= 25
    elif mem >= 80: score -= 15
    elif mem >= 70: score -= 8

    score -= min(20.0, errs * 2.0)
    score -= min(15.0, failed * 5.0)
    score -= min(20.0, not_ready * 10.0)

    metrics["health_score"] = float(max(0.0, round(score, 1)))

    artifacts = {
        "meta.txt": meta,
        "uname.txt": uname,
        "os_release.txt": os_release,
        "df.txt": df_txt,
        "free.txt": free_txt,
        "log_tail.txt": log_tail,
        "systemd_running_services.txt": running_services,
        "systemd_failed_units.txt": failed_units,
        "k8s_nodes.txt": k8s_nodes,
        "k8s_pods.txt": k8s_pods,
    }

    run_info = {
        "id": run_id,
        "created_at": created_at,
        "host": host,
        "archive_name": archive_name,
        "uname": uname.strip()[:5000],
        "os_release": os_release.strip()[:5000],
    }
    return run_info, metrics, artifacts
