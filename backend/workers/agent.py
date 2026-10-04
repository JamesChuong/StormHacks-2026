"""Agent worker: runs one agent on one challenge attempt, streaming code as events."""
import json
import logging
import os
import socket
import time

from arena import agent_runner, bus, challenges

log = logging.getLogger("agent-worker")


def run_agent(job):
    mid, aid = job["match_id"], job["agent_id"]
    if time.time() > job["deadline"]:
        return
    agent = json.loads(bus.r.hget(bus.agents_key(mid), str(aid)))
    challenge = challenges.get(job["challenge_id"])

    bus.publish(mid, "code_reset", agent_id=aid, attempt=job["attempt"])
    buf = agent_runner.ChunkBuffer(lambda text: bus.publish(mid, "code", agent_id=aid, chunk=text))
    code, tokens = agent_runner.solve(agent, challenge, job["attempt"], job["feedback"], buf.add)
    buf.flush()

    submitted_at = time.time()
    total_tokens = job["tokens"] + tokens
    bus.publish(mid, "submission", agent_id=aid, attempt=job["attempt"], tokens=total_tokens)
    bus.enqueue(bus.SANDBOX_JOBS, {**job, "code": code, "tokens": total_tokens,
                                   "submitted_at": submitted_at})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    bus.consume(bus.AGENT_JOBS, "agent-workers", f"{socket.gethostname()}-{os.getpid()}", run_agent)
