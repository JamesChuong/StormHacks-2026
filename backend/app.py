from gevent import monkey

monkey.patch_all()

import json  # noqa: E402
import logging  # noqa: E402
import time  # noqa: E402

from flask import Flask, jsonify, request  # noqa: E402
from flask_cors import CORS  # noqa: E402
from flask_socketio import SocketIO, emit, join_room  # noqa: E402

from arena import (agent_runner, betting, bus, challenges, config, judge,  # noqa: E402
                   matchmaking, orchestrator, ratings, scoring)
from arena.bus import r  # noqa: E402
from arena.db import Agent, Match, MatchEvent, Session, User, init_db  # noqa: E402

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("api")

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="gevent")


@app.teardown_appcontext
def remove_session(_exc=None):
    Session.remove()


def err(msg, code=400):
    return jsonify({"error": msg}), code


# ---------------------------------------------------------------- live fan-out

def pump_events(match_id):
    """Read the match stream and emit every event to the match's SocketIO room."""
    last = "0-0"
    while True:
        resp = r.xread({bus.events_key(match_id): last}, block=5000, count=200)
        for _, entries in resp or []:
            for event_id, fields in entries:
                last = event_id
                ev = bus.decode_event(event_id, fields)
                socketio.emit("event", ev, to=f"match:{match_id}")
                if ev["type"] == "stage" and ev["data"]["stage"] in ("settled", "error"):
                    return


def spawn_match(fn, match_id):
    socketio.start_background_task(pump_events, match_id)
    socketio.start_background_task(fn, match_id)


@socketio.on("join")
def on_join(data):
    match_id = int(data["match_id"])
    join_room(f"match:{match_id}")
    state = r.hgetall(bus.state_key(match_id))
    start = state.get("challenge_stream_id", "-")
    catchup = [bus.decode_event(eid, f) for eid, f in r.xrange(bus.events_key(match_id), min=start)]
    emit("snapshot", {"state": state, "leaderboard": orchestrator.leaderboard(match_id),
                      "events": catchup})


# ---------------------------------------------------------------- REST API

@app.get("/api/health")
def health():
    return {"ok": True, "redis": r.ping(), "gemini": bool(config.GEMINI_API_KEY),
            "sandbox": "piston" if config.PISTON_URL else "local"}


@app.post("/api/login")
def login():
    username = (request.json or {}).get("username", "").strip()[:40]
    if not username:
        return err("username required")
    s = Session()
    user = s.query(User).filter_by(username=username).first()
    if not user:
        user = User(username=username, points=config.STARTING_POINTS)
        s.add(user)
        s.commit()
    return user.to_dict()


@app.get("/api/users/<int:user_id>")
def get_user(user_id):
    user = Session().get(User, user_id)
    return user.to_dict() if user else err("not found", 404)


@app.get("/api/meta")
def meta():
    return {"models": config.ALLOWED_MODELS, "skill_templates": agent_runner.SKILL_TEMPLATES,
            "max_prompt_chars": config.MAX_PROMPT_CHARS, "max_skills": config.MAX_SKILLS}


@app.get("/api/agents")
def list_agents():
    q = Session().query(Agent)
    if request.args.get("user_id"):
        q = q.filter_by(user_id=int(request.args["user_id"]))
    return jsonify([a.to_dict() for a in q.order_by(Agent.id)])


@app.post("/api/agents")
def create_agent():
    body = request.json or {}
    if body.get("model") not in config.ALLOWED_MODELS:
        return err("unknown model")
    if not body.get("name") or not body.get("user_id"):
        return err("name and user_id required")
    if len(body.get("system_prompt", "")) > config.MAX_PROMPT_CHARS:
        return err(f"system prompt over {config.MAX_PROMPT_CHARS} chars")
    skills = [{"name": str(s["name"])[:60], "instructions": str(s["instructions"])[:500]}
              for s in body.get("skills", [])[:config.MAX_SKILLS] if s.get("name")]
    s = Session()
    agent = Agent(user_id=body["user_id"], name=body["name"][:60], model=body["model"],
                  system_prompt=body.get("system_prompt", ""), skills=skills)
    s.add(agent)
    s.commit()
    return agent.to_dict(), 201


@app.get("/api/leaderboard")
def rating_leaderboard():
    agents = Session().query(Agent).filter(Agent.matches_played > 0).all()
    return jsonify(sorted((a.to_dict() for a in agents), key=lambda a: -a["rating"]))


@app.post("/api/queue")
def join_queue():
    agent_id = int((request.json or {})["agent_id"])
    if not Session().get(Agent, agent_id):
        return err("unknown agent", 404)
    matchmaking.join(agent_id)
    return matchmaking.status(agent_id)


@app.delete("/api/queue/<int:agent_id>")
def leave_queue(agent_id):
    matchmaking.leave(agent_id)
    return matchmaking.status(agent_id)


@app.get("/api/queue/<int:agent_id>")
def queue_status(agent_id):
    return matchmaking.status(agent_id)


@app.post("/api/matches/demo")
def demo_match():
    """Start a match right away: house agents, plus the caller's agent if given."""
    s = Session()
    house = s.query(User).filter_by(username="house").one()
    agent_ids = [a.id for a in s.query(Agent).filter_by(user_id=house.id)]
    if (request.json or {}).get("agent_id"):
        agent_ids = [int(request.json["agent_id"])] + agent_ids[:2]
    match = orchestrator.create_match(agent_ids, spawn_match)
    return match.to_dict(), 201


@app.get("/api/matches")
def list_matches():
    matches = Session().query(Match).order_by(Match.id.desc()).limit(20)
    return jsonify([m.to_dict() for m in matches])


@app.get("/api/matches/<int:match_id>")
def get_match(match_id):
    s = Session()
    match = s.get(Match, match_id)
    if not match:
        return err("not found", 404)
    agents = s.query(Agent).filter(Agent.id.in_(match.agent_ids)).all()
    owners = {u.id: u.username for u in s.query(User).filter(User.id.in_([a.user_id for a in agents]))}
    board = orchestrator.leaderboard(match_id)
    if not board:  # Redis keys expired: rebuild from results
        from arena.db import MatchResult
        board = [{"agent_id": mr.agent_id, "points": mr.points} for mr in
                 s.query(MatchResult).filter_by(match_id=match_id).order_by(MatchResult.rank)]
    return {
        **match.to_dict(),
        "state": r.hgetall(bus.state_key(match_id)),
        "agents": [{**a.to_dict(), "owner": owners.get(a.user_id)} for a in agents],
        "leaderboard": board,
        "pool": betting.pool(s, match_id),
        "win_probability": ratings.win_probabilities(agents),
    }


@app.get("/api/matches/<int:match_id>/events")
def match_events(match_id):
    events = (Session().query(MatchEvent).filter_by(match_id=match_id)
              .order_by(MatchEvent.id).all())
    return jsonify([{"id": e.stream_id, "type": e.type, "data": e.data, "ts": e.ts.timestamp()}
                    for e in events])


@app.get("/api/matches/<int:match_id>/reveal")
def reveal(match_id):
    match = Session().get(Match, match_id)
    if not match:
        return err("not found", 404)
    if match.stage not in ("revealing", "settled"):
        return err("not revealed yet", 403)
    return {"commit_hash": match.commit_hash, "payload": match.reveal_payload}


@app.post("/api/matches/<int:match_id>/bets")
def place_bet(match_id):
    body = request.json or {}
    s = Session()
    match = s.get(Match, match_id)
    if not match:
        return err("not found", 404)
    try:
        user = betting.place_bet(s, match, int(body["user_id"]), int(body["agent_id"]),
                                 int(body["amount"]))
    except betting.BetError as e:
        return err(str(e))
    pool = betting.pool(s, match_id)
    bus.publish(match_id, "pool", pool=pool)
    return {"user": user.to_dict(), "pool": pool}


@app.post("/api/dev/run-sync")
def run_sync():
    """Phase 1 check: run house agents through every challenge synchronously, no queues."""
    s = Session()
    house = s.query(User).filter_by(username="house").one()
    agents = [orchestrator.agent_config(a) for a in s.query(Agent).filter_by(user_id=house.id)]
    report, totals = [], {a["id"]: 0.0 for a in agents}
    for ch in challenges.load_all().values():
        results = []
        for agent in agents:
            start, tokens, feedback, best = time.time(), 0, "", None
            for attempt in range(1, config.MAX_ATTEMPTS + 1):
                code, used = agent_runner.solve(agent, ch, attempt, feedback)
                tokens += used
                res = judge.evaluate(code, ch)
                if best is None or res["pass_rate"] > best["pass_rate"]:
                    best = {**res, "solve_time": time.time() - start}
                if res["pass_rate"] == 1:
                    break
                feedback = res["feedback"]
            results.append({"agent": agent["id"], "pass_rate": best["pass_rate"],
                            "solve_time": best["solve_time"], "tokens": tokens,
                            "attempts": attempt})
        points = scoring.score_challenge(results)
        for aid, pts in points.items():
            totals[aid] += pts
        report.append({"challenge": ch["id"], "results": results, "points": points})
    return {"challenges": report, "scoreboard": sorted(
        ({"agent": a["name"], "points": round(totals[a["id"]], 2)} for a in agents),
        key=lambda x: -x["points"])}


# ---------------------------------------------------------------- startup

def seed():
    s = Session()
    # Move agents off retired models (e.g. gemini-2.5-*) so they don't 404.
    fallback = config.DEFAULT_MODEL if config.GEMINI_API_KEY else "mock"
    s.query(Agent).filter(Agent.model.notin_(config.ALLOWED_MODELS)).update(
        {Agent.model: fallback}, synchronize_session=False)
    s.commit()
    if s.query(User).filter_by(username="house").first():
        Session.remove()
        return
    house = User(username="house", points=0)
    s.add(house)
    s.flush()
    model = config.DEFAULT_MODEL if config.GEMINI_API_KEY else "mock"
    s.add_all([
        Agent(user_id=house.id, name="Baseline Bot", model=model, system_prompt="", skills=[]),
        Agent(user_id=house.id, name="Edge-Case Hunter", model=model,
              system_prompt="You are meticulous and value correctness over speed.",
              skills=agent_runner.SKILL_TEMPLATES[:2]),
    ])
    s.commit()
    Session.remove()


init_db()
seed()
socketio.start_background_task(matchmaking.loop, spawn_match)

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000)
