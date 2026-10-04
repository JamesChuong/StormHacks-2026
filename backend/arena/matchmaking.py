"""Queue: a match starts when 4 agents wait, or 2+ have waited MM_WAIT_SECONDS."""
import logging
import time

from . import config, orchestrator
from .bus import r

log = logging.getLogger(__name__)

QUEUE = "mm:queue"  # sorted set: agent_id -> enqueue time
MAX_PLAYERS = 4


def assigned_key(agent_id):
    return f"mm:assigned:{agent_id}"


def join(agent_id):
    r.delete(assigned_key(agent_id))
    r.zadd(QUEUE, {str(agent_id): time.time()}, nx=True)


def leave(agent_id):
    r.zrem(QUEUE, str(agent_id))


def status(agent_id):
    match_id = r.get(assigned_key(agent_id))
    return {
        "waiting": r.zscore(QUEUE, str(agent_id)) is not None,
        "match_id": int(match_id) if match_id else None,
        "queue_size": r.zcard(QUEUE),
    }


def tick(spawn):
    waiting = r.zrange(QUEUE, 0, MAX_PLAYERS - 1, withscores=True)
    if len(waiting) < 2:
        return
    oldest = waiting[0][1]
    if len(waiting) < MAX_PLAYERS and time.time() - oldest < config.MM_WAIT_SECONDS:
        return
    agent_ids = [int(aid) for aid, _ in waiting]
    r.zrem(QUEUE, *[str(a) for a in agent_ids])
    match = orchestrator.create_match(agent_ids, spawn)
    for aid in agent_ids:
        r.set(assigned_key(aid), match.id, ex=3600)
    log.info("matched agents %s into match %s", agent_ids, match.id)


def loop(spawn):
    while True:
        try:
            tick(spawn)
        except Exception:
            log.exception("matchmaking tick failed")
        time.sleep(2)
