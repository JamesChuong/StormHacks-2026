"""Redis Streams helpers: work queues (consumer groups) and per-match event streams."""
import json
import logging
import time

import redis

from . import config

log = logging.getLogger(__name__)

r = redis.Redis.from_url(config.REDIS_URL, decode_responses=True)

AGENT_JOBS = "jobs:agent"
SANDBOX_JOBS = "jobs:sandbox"
ACTIVE_MATCHES = "matches:active"
EVENT_MAXLEN = 20000


def events_key(match_id):
    return f"match:{match_id}:events"


def state_key(match_id):
    return f"match:{match_id}:state"


def leaderboard_key(match_id):
    return f"match:{match_id}:leaderboard"


def agents_key(match_id):
    return f"match:{match_id}:agents"


def results_key(match_id, challenge_index):
    return f"match:{match_id}:results:{challenge_index}"


def publish(match_id, type_, **data):
    """Append an event to the match stream; returns the stream ID."""
    return r.xadd(
        events_key(match_id),
        {"type": type_, "data": json.dumps(data), "ts": str(time.time())},
        maxlen=EVENT_MAXLEN,
        approximate=True,
    )


def decode_event(event_id, fields):
    return {
        "id": event_id,
        "type": fields["type"],
        "data": json.loads(fields["data"]),
        "ts": float(fields["ts"]),
    }


def enqueue(stream, payload):
    return r.xadd(stream, {"payload": json.dumps(payload)})


def ensure_group(stream, group, start_id="0"):
    try:
        r.xgroup_create(stream, group, id=start_id, mkstream=True)
    except redis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


def consume(stream, group, consumer, handler):
    """Run forever: each job goes to exactly one worker; stale jobs are reclaimed."""
    ensure_group(stream, group)
    log.info("%s consuming %s as %s", group, stream, consumer)
    while True:
        _, stale, _ = r.xautoclaim(stream, group, consumer, min_idle_time=60_000,
                                   start_id="0-0", count=5)
        fresh = r.xreadgroup(group, consumer, {stream: ">"}, count=1, block=5000)
        jobs = stale + [m for _, msgs in (fresh or []) for m in msgs]
        for job_id, fields in jobs:
            if not fields:
                continue
            try:
                handler(json.loads(fields["payload"]))
            except Exception:
                # Ack anyway so one poison job can't loop forever.
                log.exception("job %s on %s failed", job_id, stream)
            r.xack(stream, group, job_id)
