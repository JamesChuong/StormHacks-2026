"""Sandbox worker: judges submissions, records results idempotently, requeues retries."""
import json
import logging
import os
import socket
import time

from arena import bus, challenges, config, judge, sandbox

log = logging.getLogger("sandbox-worker")


def run_submission(job):
    mid, idx, aid, attempt = job["match_id"], job["challenge_index"], job["agent_id"], job["attempt"]
    challenge = challenges.get(job["challenge_id"])
    result = judge.evaluate(job["code"], challenge)

    # Consumer groups deliver at least once: only record each attempt one time.
    if not bus.r.set(f"scored:{mid}:{idx}:{aid}:{attempt}", 1, nx=True, ex=3600):
        return

    on_time = job["submitted_at"] <= job["deadline"]
    pass_rate = result["pass_rate"] if on_time else 0.0
    final = pass_rate == 1 or attempt >= config.MAX_ATTEMPTS or time.time() >= job["deadline"]

    key = bus.results_key(mid, idx)
    prev = json.loads(bus.r.hget(key, str(aid)) or "null") or {"pass_rate": 0.0, "solve_time": None}
    best = pass_rate > prev["pass_rate"]
    entry = {
        "pass_rate": pass_rate if best else prev["pass_rate"],
        "solve_time": (job["submitted_at"] - job["released_at"]) if pass_rate == 1 else prev["solve_time"],
        "tokens": job["tokens"],
        "attempts": attempt,
        "final": final,
    }
    bus.r.hset(key, str(aid), json.dumps(entry))
    bus.publish(mid, "test_result", agent_id=aid, attempt=attempt, passed=result["passed"],
                total=result["total"], examples_passed=result["examples_passed"],
                examples_total=result["examples_total"], timeouts=result["timeouts"],
                final=final, on_time=on_time)

    if not final:
        bus.enqueue(bus.AGENT_JOBS, {k: job[k] for k in (
            "match_id", "challenge_index", "challenge_id", "agent_id", "tokens",
            "released_at", "deadline")} | {"attempt": attempt + 1, "feedback": result["feedback"]})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sandbox.ensure_piston_runtime()
    bus.consume(bus.SANDBOX_JOBS, "sandbox-workers", f"{socket.gethostname()}-{os.getpid()}",
                run_submission)
