"use client";

import { use, useEffect, useState } from "react";
import { api } from "@/lib/api";

async function sha256(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export default function Verify({ params }) {
  const { id } = use(params);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api(`/api/matches/${id}/reveal`)
      .then(async ({ commit_hash, payload }) => {
        const computed = await sha256(payload);
        setResult({ commit_hash, computed, revealed: JSON.parse(payload) });
      })
      .catch((e) => setError(e.message));
  }, [id]);

  return (
    <div className="panel">
      <h2>Verify match #{id}</h2>
      <p className="muted">
        Before betting opened, the platform committed to a SHA-256 hash of the challenges and hidden tests.
        Your browser hashes the revealed payload below and compares the result with that commitment.
      </p>
      {error && <p className="error">{error}</p>}
      {result && (
        <>
          <p>Committed: <span className="mono">{result.commit_hash}</span></p>
          <p>Computed: <span className="mono">{result.computed}</span></p>
          <h3>{result.computed === result.commit_hash
            ? <span className="badge good">✓ Match: challenges were not changed</span>
            : <span className="badge bad">✗ Mismatch</span>}</h3>
          {result.revealed.challenges.map((c) => (
            <div key={c.id} className="panel">
              <b>{c.title}</b> <span className="muted">{c.hidden_tests.length} hidden tests</span>
              <pre>{c.statement}</pre>
            </div>
          ))}
        </>
      )}
      <a href={`/match/${id}`}>← back to match</a>
    </div>
  );
}
