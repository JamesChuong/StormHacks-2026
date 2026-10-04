"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, loadUser, saveUser } from "@/lib/api";

function Login({ onLogin }) {
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    try {
      const user = await api("/api/login", { method: "POST", body: { username: name } });
      saveUser(user);
      onLogin(user);
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <form className="panel" onSubmit={submit}>
      <h2>Sign in</h2>
      <div className="row">
        <input placeholder="username" value={name} onChange={(e) => setName(e.target.value)} style={{ flex: 1 }} />
        <button>Enter arena</button>
      </div>
      {error && <p className="error">{error}</p>}
    </form>
  );
}

function AgentBuilder({ user, meta, onCreated }) {
  const [name, setName] = useState("");
  const [model, setModel] = useState(meta.models[0]);
  const [prompt, setPrompt] = useState("");
  const [skills, setSkills] = useState([]);
  const [error, setError] = useState("");

  const updateSkill = (i, field, value) =>
    setSkills(skills.map((s, j) => (i === j ? { ...s, [field]: value } : s)));

  const submit = async (e) => {
    e.preventDefault();
    try {
      await api("/api/agents", {
        method: "POST",
        body: { user_id: user.id, name, model, system_prompt: prompt, skills },
      });
      setName(""); setPrompt(""); setSkills([]); setError("");
      onCreated();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <form className="panel" onSubmit={submit}>
      <h2>Build an agent</h2>
      <label>Name</label>
      <input value={name} onChange={(e) => setName(e.target.value)} required />
      <label>Model</label>
      <select value={model} onChange={(e) => setModel(e.target.value)}>
        {meta.models.map((m) => <option key={m}>{m}</option>)}
      </select>
      <label>System prompt ({prompt.length}/{meta.max_prompt_chars})</label>
      <textarea value={prompt} maxLength={meta.max_prompt_chars} onChange={(e) => setPrompt(e.target.value)}
        placeholder="e.g. You are a careful competitive programmer..." />
      <label>Skills ({skills.length}/{meta.max_skills})</label>
      {skills.map((s, i) => (
        <div key={i} className="panel" style={{ padding: 8 }}>
          <div className="row">
            <input value={s.name} placeholder="skill name" onChange={(e) => updateSkill(i, "name", e.target.value)} style={{ flex: 1 }} />
            <button type="button" className="secondary" onClick={() => setSkills(skills.filter((_, j) => j !== i))}>✕</button>
          </div>
          <textarea value={s.instructions} placeholder="instructions applied to every challenge"
            onChange={(e) => updateSkill(i, "instructions", e.target.value)} />
        </div>
      ))}
      <div className="row">
        <button type="button" className="secondary" disabled={skills.length >= meta.max_skills}
          onClick={() => setSkills([...skills, { name: "", instructions: "" }])}>+ Blank skill</button>
        {meta.skill_templates.map((t) => (
          <button key={t.name} type="button" className="secondary" disabled={skills.length >= meta.max_skills}
            onClick={() => setSkills([...skills, { ...t }])}>+ {t.name}</button>
        ))}
      </div>
      <div style={{ marginTop: 12 }}><button>Create agent</button></div>
      {error && <p className="error">{error}</p>}
    </form>
  );
}

function MyAgents({ agents }) {
  const router = useRouter();
  const [queued, setQueued] = useState({});

  useEffect(() => {
    const waiting = Object.keys(queued).filter((id) => queued[id]);
    if (!waiting.length) return;
    const t = setInterval(async () => {
      for (const id of waiting) {
        const s = await api(`/api/queue/${id}`);
        if (s.match_id) router.push(`/match/${s.match_id}`);
      }
    }, 2000);
    return () => clearInterval(t);
  }, [queued, router]);

  const join = async (id) => {
    await api("/api/queue", { method: "POST", body: { agent_id: id } });
    setQueued({ ...queued, [id]: true });
  };
  const leave = async (id) => {
    await api(`/api/queue/${id}`, { method: "DELETE" });
    setQueued({ ...queued, [id]: false });
  };
  const demo = async (id) => {
    const m = await api("/api/matches/demo", { method: "POST", body: { agent_id: id } });
    router.push(`/match/${m.id}`);
  };

  return (
    <div className="panel">
      <h2>My agents</h2>
      {!agents.length && <p className="muted">No agents yet. Build one!</p>}
      <table>
        <tbody>
          {agents.map((a) => (
            <tr key={a.id}>
              <td><b>{a.name}</b><div className="muted">{a.model} · {a.skills.length} skills · rating {a.rating}</div></td>
              <td style={{ textAlign: "right" }}>
                {queued[a.id]
                  ? <><span className="badge warn">in queue…</span> <button className="secondary" onClick={() => leave(a.id)}>Leave</button></>
                  : <><button onClick={() => join(a.id)}>Join queue</button> <button className="secondary" onClick={() => demo(a.id)}>vs house bots</button></>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Home() {
  const [user, setUser] = useState(null);
  const [meta, setMeta] = useState(null);
  const [agents, setAgents] = useState([]);
  const [matches, setMatches] = useState([]);
  const [board, setBoard] = useState([]);
  const router = useRouter();

  const refresh = async (u = user) => {
    setMatches(await api("/api/matches"));
    setBoard(await api("/api/leaderboard"));
    if (u) {
      setAgents(await api(`/api/agents?user_id=${u.id}`));
      const fresh = await api(`/api/users/${u.id}`);
      setUser(fresh);
      saveUser(fresh);
    }
  };

  useEffect(() => {
    const u = loadUser();
    setUser(u);
    api("/api/meta").then(setMeta);
    refresh(u);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const spectateDemo = async () => {
    const m = await api("/api/matches/demo", { method: "POST", body: {} });
    router.push(`/match/${m.id}`);
  };

  return (
    <div className="grid">
      <div>
        {!user ? <Login onLogin={(u) => { setUser(u); refresh(u); }} /> : (
          <div className="panel row" style={{ justifyContent: "space-between" }}>
            <span>Signed in as <b>{user.username}</b> · <b>{user.points}</b> points</span>
            <button className="secondary" onClick={() => { saveUser(null); setUser(null); setAgents([]); }}>Sign out</button>
          </div>
        )}
        {user && meta && <AgentBuilder user={user} meta={meta} onCreated={() => refresh()} />}
      </div>
      <div>
        {user && <MyAgents agents={agents} />}
        <div className="panel">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h2>Matches</h2>
            <button className="secondary" onClick={spectateDemo}>Start house-bot match</button>
          </div>
          <table>
            <tbody>
              {matches.map((m) => (
                <tr key={m.id}>
                  <td><a href={`/match/${m.id}`}>Match #{m.id}</a></td>
                  <td><span className="badge">{m.stage}</span></td>
                  <td className="muted">{m.agent_ids.length} agents</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="panel">
          <h2>Agent ratings (TrueSkill)</h2>
          <table>
            <thead><tr><th>Agent</th><th>μ ± σ</th><th>Rating</th><th>Matches</th></tr></thead>
            <tbody>
              {board.map((a) => (
                <tr key={a.id}><td>{a.name}</td><td>{a.mu} ± {a.sigma}</td><td>{a.rating}</td><td>{a.matches_played}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
