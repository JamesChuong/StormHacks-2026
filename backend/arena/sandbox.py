"""Run submitted code against test cases via Piston (or a local subprocess in dev)."""
import logging
import resource
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from . import config

log = logging.getLogger(__name__)


def _run_piston(code, stdin, timeout_ms, mem_mb):
    resp = requests.post(f"{config.PISTON_URL}/api/v2/execute", json={
        "language": "python",
        "version": "*",
        "files": [{"name": "main.py", "content": code}],
        "stdin": stdin,
        "run_timeout": timeout_ms,
        "run_memory_limit": mem_mb * 1024 * 1024,
    }, timeout=30)
    resp.raise_for_status()
    run = resp.json()["run"]
    return {
        "stdout": run.get("stdout", ""),
        "stderr": run.get("stderr", "")[-500:],
        "timed_out": run.get("signal") == "SIGKILL",
        "exit_ok": run.get("code") == 0,
    }


def _run_local(code, stdin, timeout_ms, mem_mb):
    def limit():
        resource.setrlimit(resource.RLIMIT_AS, (mem_mb * 1024 * 1024,) * 2)

    try:
        proc = subprocess.run([sys.executable, "-c", code], input=stdin, capture_output=True,
                              text=True, timeout=timeout_ms / 1000, preexec_fn=limit)
        return {"stdout": proc.stdout, "stderr": proc.stderr[-500:],
                "timed_out": False, "exit_ok": proc.returncode == 0}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "Time limit exceeded", "timed_out": True, "exit_ok": False}


def run_one(code, stdin, timeout_ms=3000, mem_mb=256):
    start = time.time()
    runner = _run_piston if config.PISTON_URL else _run_local
    out = runner(code, stdin, timeout_ms, mem_mb)
    out["time_ms"] = int((time.time() - start) * 1000)
    return out


def outputs_match(got, expected):
    return got.split() == expected.split()


def run_tests(code, tests, challenge):
    """Return one result dict per test, in order."""
    def one(test):
        out = run_one(code, test["input"], challenge.get("run_timeout_ms", 3000),
                      challenge.get("memory_limit_mb", 256))
        out["passed"] = out["exit_ok"] and outputs_match(out["stdout"], test["output"])
        return out

    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(one, tests))


def ensure_piston_runtime():
    """Install the Python runtime into Piston if it isn't there yet."""
    if not config.PISTON_URL:
        log.warning("PISTON_URL not set: running code in local subprocesses (NOT sandboxed)")
        return
    for _ in range(60):
        try:
            runtimes = requests.get(f"{config.PISTON_URL}/api/v2/runtimes", timeout=5).json()
            break
        except requests.RequestException:
            time.sleep(2)
    else:
        raise RuntimeError("Piston not reachable")
    if any(rt["language"] == "python" for rt in runtimes):
        return
    log.info("Installing Python %s into Piston...", config.PISTON_PYTHON_VERSION)
    requests.post(f"{config.PISTON_URL}/api/v2/packages",
                  json={"language": "python", "version": config.PISTON_PYTHON_VERSION},
                  timeout=600).raise_for_status()
