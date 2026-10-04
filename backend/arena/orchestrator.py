"""Match state machine: scheduled -> betting_open -> locked -> running -> revealing -> settled."""
import hashlib
import json
import logging
import time
from datetime import datetime, timezone

from . import betting, bus, chain, challenges, config, ratings, scoring
from .bus import r
from .db import Agent, Match, MatchResult, Session

log = logging.getLogger(__name__)


def agent_config(agent):
    return {"id": agent.id, "name": agent.name, "model": agent.model,
            "system_prompt": agent.system_prompt, "skills": agent.skills}


def create_match(agent_ids, spawn):
    """Create the match, commit to a challenge set, and start running it via spawn(fn, *args)."""
    s = Session()
    agents = s.query(Agent).filter(Agent.id.in_(agent_ids)).all()
    if len(agents) < 2:
        raise ValueError("a match needs at least 2 agents")
    ch_ids = challenges.pick(config.CHALLENGES_PER_MATCH)
    payload, commit_hash = challenges.commit(ch_ids)
    match = Match(stage="scheduled", agent_ids=[a.id for a in agents], challenge_ids=ch_ids,
                  commit_hash=commit_hash, reveal_payload=payload)
    s.add(match)
    s.commit()

    r.hset(bus.agents_key(match.id),
           mapping={str(a.id): json.dumps(agent_config(a)) for a in agents})
    r.hset(bus.state_key(match.id), mapping={"stage": "scheduled", "commit_hash": commit_hash})
    r.zadd(bus.leaderboard_key(match.id), {str(a.id): 0 for a in agents})
    r.sadd(bus.ACTIVE_MATCHES, match.id)
    spawn(run_match, match.id)
    return match


def set_stage(match_id, stage, **extra):
    r.hset(bus.state_key(match_id), mapping={"stage": stage, **{k: str(v) for k, v in extra.items()}})
    s = Session()
    s.get(Match, match_id).stage = stage
    s.commit()
    bus.publish(match_id, "stage", stage=stage, **extra)


def leaderboard(match_id):
    return [{"agent_id": int(aid), "points": round(pts, 2)}
            for aid, pts in r.zrevrange(bus.leaderboard_key(match_id), 0, -1, withscores=True)]


def run_match(match_id):
    try:
        s = Session()
        match = s.get(Match, match_id)

        set_stage(match_id, "betting_open", closes_at=time.time() + config.BETTING_SECONDS,
                  commit_hash=match.commit_hash)
        chain.create_match(match_id, match.commit_hash, len(match.agent_ids))
        time.sleep(config.BETTING_SECONDS)

        set_stage(match_id, "locked")
        chain.lock(match_id)

        set_stage(match_id, "running")
        for idx, cid in enumerate(match.challenge_ids):
            run_challenge(match_id, idx, cid, match.agent_ids, len(match.challenge_ids))

        set_stage(match_id, "revealing")
        reveal_hash = hashlib.sha256(match.reveal_payload.encode()).hexdigest()
        # The payload itself is large; clients fetch it from /api/matches/<id>/reveal.
        bus.publish(match_id, "reveal", hash=reveal_hash, commit_hash=match.commit_hash)

        winner = settle(match_id)
        chain.resolve(match_id, match.agent_ids.index(winner), reveal_hash)
        set_stage(match_id, "settled", winner_agent_id=winner)
    except Exception:
        log.exception("match %s failed", match_id)
        set_stage(match_id, "error")
    finally:
        Session.remove()


def run_challenge(match_id, idx, challenge_id, agent_ids, total):
    ch = challenges.get(challenge_id)
    released = time.time()
    deadline = released + ch["time_limit_s"]
    stream_id = bus.publish(match_id, "challenge_start", index=idx, total=total,
                            challenge=challenges.public_view(ch), deadline=deadline)
    # Late joiners catch up from here.
    r.hset(bus.state_key(match_id), mapping={
        "challenge_index": idx, "challenge_stream_id": stream_id, "deadline": deadline})

    for aid in agent_ids:
        bus.enqueue(bus.AGENT_JOBS, {
            "match_id": match_id, "challenge_index": idx, "challenge_id": challenge_id,
            "agent_id": aid, "attempt": 1, "feedback": "", "tokens": 0,
            "released_at": released, "deadline": deadline,
        })

    key = bus.results_key(match_id, idx)
    # Small grace period so an in-flight sandbox run can finish.
    while time.time() < deadline + 10:
        res = r.hgetall(key)
        if all(str(a) in res and json.loads(res[str(a)])["final"] for a in agent_ids):
            break
        time.sleep(0.5)

    res = r.hgetall(key)
    results = []
    for aid in agent_ids:
        entry = json.loads(res[str(aid)]) if str(aid) in res else {}
        results.append({"agent": aid, "pass_rate": entry.get("pass_rate", 0.0),
                        "solve_time": entry.get("solve_time"), "tokens": entry.get("tokens", 0),
                        "attempts": entry.get("attempts", 0)})
    points = scoring.score_challenge(results)
    for aid, pts in points.items():
        r.zincrby(bus.leaderboard_key(match_id), pts, str(aid))
    bus.publish(match_id, "challenge_end", index=idx,
                points={str(k): v for k, v in points.items()}, results=results)
    bus.publish(match_id, "score", leaderboard=leaderboard(match_id))


def settle(match_id):
    s = Session()
    match = s.get(Match, match_id)
    board = leaderboard(match_id)
    winner = board[0]["agent_id"]

    agents = {a.id: a for a in s.query(Agent).filter(Agent.id.in_(match.agent_ids))}
    for rank, row in enumerate(board, start=1):
        s.add(MatchResult(match_id=match_id, agent_id=row["agent_id"],
                          points=row["points"], rank=rank))
    ratings.update([agents[row["agent_id"]] for row in board])
    match.winner_agent_id = winner
    match.settled_at = datetime.now(timezone.utc)
    s.commit()
    betting.settle(s, match_id, winner)
    return winner
