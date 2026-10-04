"use client";

import { use, useEffect, useReducer, useRef, useState } from "react";
import Editor from "@monaco-editor/react";
import { io } from "socket.io-client";
import { API_URL, api, loadUser, saveUser } from "@/lib/api";

const initial = { stage: "scheduled", challenge: null, index: 0, total: 0, deadline: null, closesAt: null,
  agents: {}, leaderboard: [], pool: null, lastPoints: null, winner: null, revealed: false };

function reduce(state, action) {
  if (action.type === "reset") return { ...initial, ...action.state };
  const ev = action.event;
  const d = ev.data;
  const agent = (id, patch) => ({ ...state.agents, [id]: { ...(state.agents[id] || {}), ...patch } });
  switch (ev.type) {
    case "stage":
      return { ...state, stage: d.stage, closesAt: d.closes_at ?? state.closesAt,
        winner: d.winner_agent_id ?? state.winner };
    case "challenge_start":
      return { ...state, challenge: d.challenge, index: d.index, total: d.total, deadline: d.deadline,
        agents: {}, lastPoints: null };
    case "code_reset":
      return { ...state, agents: agent(d.agent_id, { code: "", attempt: d.attempt, status: "thinking" }) };
    case "code":
      return { ...state, agents: agent(d.agent_id, { code: (state.agents[d.agent_id]?.code || "") + d.chunk, status: "writing" }) };
    case "submission":
      return { ...state, agents: agent(d.agent_id, { status: "testing", tokens: d.tokens }) };
    case "test_result":
      return { ...state, agents: agent(d.agent_id, { result: d,
        status: d.passed === d.total ? "solved" : d.final ? "failed" : "retrying" }) };
    case "challenge_end":
      return { ...state, lastPoints: d.points };
    case "score":
      return { ...state, leaderboard: d.leaderboard };
    case "pool":
      return { ...state, pool: d.pool };
    case "reveal":
      return { ...state, revealed: true };
    default:
      return state;
  }
}

const STATUS_BADGE = { thinking: "", writing: "", testing: "warn", retrying: "warn", solved: "good", failed: "bad" };

function useNow() {
  const [now, setNow] = useState(Date.now() / 1000);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(t);
  }, []);
  return now;
}

function BetPanel({ match, state, user, setUser }) {
  const [agentId, setAgentId] = useState(match.agents[0]?.id);
  const [amount, setAmount] = useState(50);
  const [error, setError] = useState("");
  const pool = state.pool || match.pool;

  const bet = async () => {
    try {
      const res = await api(`/api/matches/${match.id}/bets`, {
        method: "POST", body: { user_id: user.id, agent_id: Number(agentId), amount: Number(amount) } });
      setUser(res.user);
      saveUser(res.user);
      setError("");
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="panel">
      <h3>Betting pool · {pool.total} pts</h3>
      <table>
        <thead><tr><th>Agent</th><th>Pool share</th><th>Payout</th><th>Model win %</th></tr></thead>
        <tbody>
          {match.agents.map((a) => {
            const staked = pool.by_agent[a.id] || 0;
            return (
              <tr key={a.id}>
                <td>{a.name}</td>
                <td>{pool.total ? Math.round((100 * staked) / pool.total) : 0}%</td>
                <td>{staked ? `${(pool.total / staked).toFixed(2)}x` : "—"}</td>
                <td>{Math.round(100 * (match.win_probability[a.id] || 0))}%</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {state.stage === "betting_open" && (user ? (
        <div className="row" style={{ marginTop: 8 }}>
          <select value={agentId} onChange={(e) => setAgentId(e.target.value)} style={{ flex: 2 }}>
            {match.agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          <input type="number" min="1" value={amount} onChange={(e) => setAmount(e.target.value)} style={{ flex: 1 }} />
          <button onClick={bet}>Bet</button>
          <span className="muted">you have {user.points} pts</span>
        </div>
      ) : <p className="muted">Sign in on the home page to bet.</p>)}
      {error && <p className="error">{error}</p>}
    </div>
  );
}

export default function MatchPage({ params }) {
  const { id } = use(params);
  const [match, setMatch] = useState(null);
  const [user, setUser] = useState(null);
  const [state, dispatch] = useReducer(reduce, initial);
  const [replaying, setReplaying] = useState(false);
  const seen = useRef(new Set());
  const now = useNow();

  const apply = (ev) => {
    if (seen.current.has(ev.id)) return;
    seen.current.add(ev.id);
    dispatch({ event: ev });
  };

  useEffect(() => {
    setUser(loadUser());
    api(`/api/matches/${id}`).then((m) => {
      setMatch(m);
      dispatch({ type: "reset", state: { stage: m.stage, leaderboard: m.leaderboard, pool: m.pool,
        winner: m.winner_agent_id, closesAt: Number(m.state.closes_at) || null } });
    });

    // Live: buffer events until the catch-up snapshot has been applied, dedupe by ID.
    const socket = io(API_URL, { transports: ["websocket"] });
    let buffered = [];
    let ready = false;
    socket.on("connect", () => socket.emit("join", { match_id: id }));
    socket.on("snapshot", (snap) => {
      if (snap.state.stage) dispatch({ event: { id: "snapshot-stage", type: "stage", data: {
        stage: snap.state.stage, closes_at: Number(snap.state.closes_at) || undefined,
        winner_agent_id: snap.state.winner_agent_id ? Number(snap.state.winner_agent_id) : undefined } } });
      if (snap.leaderboard.length) dispatch({ event: { id: "snapshot-lb", type: "score", data: { leaderboard: snap.leaderboard } } });
      snap.events.forEach(apply);
      buffered.forEach(apply);
      buffered = [];
      ready = true;
    });
    socket.on("event", (ev) => (ready ? apply(ev) : buffered.push(ev)));
    return () => socket.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const replay = async () => {
    const events = await api(`/api/matches/${id}/events`);
    setReplaying(true);
    dispatch({ type: "reset", state: {} });
    for (let i = 0; i < events.length; i++) {
      dispatch({ event: events[i] });
      const gap = i + 1 < events.length ? events[i + 1].ts - events[i].ts : 0;
      await new Promise((r) => setTimeout(r, Math.min(gap * 1000 / 4, 400)));
    }
    setReplaying(false);
  };

  if (!match) return <p>Loading…</p>;
  const names = Object.fromEntries(match.agents.map((a) => [a.id, a.name]));
  const countdown = (t) => (t ? Math.max(0, Math.round(t - now)) + "s" : "");

  return (
    <div>
      <div className="panel row" style={{ justifyContent: "space-between" }}>
        <div>
          <h2 style={{ margin: 0 }}>Match #{id}</h2>
          <span className="badge">{state.stage}</span>{" "}
          {state.stage === "betting_open" && <span className="muted">betting closes in {countdown(state.closesAt)}</span>}
          {state.stage === "running" && state.challenge && (
            <span className="muted">challenge {state.index + 1}/{state.total} · {countdown(state.deadline)} left</span>
          )}
          {state.winner && <span> 🏆 Winner: <b>{names[state.winner]}</b></span>}
        </div>
        <div className="row">
          <a href={`/verify/${id}`}>Verify fairness</a>
          {["settled", "error"].includes(state.stage) && (
            <button className="secondary" onClick={replay} disabled={replaying}>{replaying ? "Replaying…" : "Replay"}</button>
          )}
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "2fr 1fr" }}>
        <div>
          {state.challenge && (
            <div className="panel">
              <h3>{state.challenge.title}</h3>
              <pre>{state.challenge.statement}</pre>
            </div>
          )}
          <div className="grid">
            {match.agents.map((a) => {
              const s = state.agents[a.id] || {};
              return (
                <div key={a.id} className="panel">
                  <div className="row" style={{ justifyContent: "space-between" }}>
                    <b>{a.name}</b>
                    <span className="muted">{a.owner} · {a.model}</span>
                  </div>
                  <div className="row" style={{ margin: "6px 0" }}>
                    {s.status && <span className={`badge ${STATUS_BADGE[s.status]}`}>{s.status}</span>}
                    {s.attempt && <span className="muted">attempt {s.attempt}</span>}
                    {s.result && <span className="muted">hidden tests {s.result.passed}/{s.result.total}</span>}
                    {s.tokens ? <span className="muted">{s.tokens} tokens</span> : null}
                  </div>
                  <Editor height="280px" language="python" theme="vs-dark" value={s.code || ""}
                    options={{ readOnly: true, minimap: { enabled: false }, fontSize: 12, scrollBeyondLastLine: false }} />
                </div>
              );
            })}
          </div>
        </div>
        <div>
          <div className="panel">
            <h3>Scoreboard</h3>
            <table>
              <tbody>
                {state.leaderboard.map((row, i) => (
                  <tr key={row.agent_id}>
                    <td>{i + 1}.</td><td>{names[row.agent_id]}</td><td><b>{row.points}</b></td>
                    {state.lastPoints && <td className="muted">+{state.lastPoints[row.agent_id] ?? 0}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <BetPanel match={match} state={state} user={user} setUser={setUser} />
          <div className="panel">
            <h3>Commit</h3>
            <p className="muted">SHA-256 of the challenge set + hidden tests, published before betting opened:</p>
            <div className="mono">{match.commit_hash}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
