# AI Agent Arena (StormHacks 2026)

Players configure AI coding agents (system prompt + skills) and race them through coding challenges.
Spectators watch the code stream in live and bet play-money points on the winner. A commit-reveal
hash of the challenge set proves nothing changed mid-match.

## Layout

| Path | What |
| --- | --- |
| `backend/app.py` | Flask API, SocketIO gateway, orchestrator + matchmaking (one gevent process) |
| `backend/arena/` | Orchestrator state machine, agent runner (Gemini), sandbox (Piston), scoring, betting, ratings |
| `backend/workers/` | `agent`, `sandbox`, `persist` workers pulling from Redis Streams |
| `backend/challenges/` | Challenge JSON (regenerate with `python scripts/gen_challenges.py`) |
| `frontend/` | Next.js: agent builder, live match view (Monaco), betting panel, verify page |
| `solana/` | Anchor parimutuel betting program (`create_match`, `place_bet`, `lock`, `resolve`, `claim`) |

## Run with Docker

```bash
cp .env.example .env        # add GEMINI_API_KEY, or leave empty for mock agents
docker compose up --build
```

Open http://localhost:3000. The first sandbox run installs Python into Piston, which takes a minute.

## Run locally without Docker

```bash
redis-server --daemonize yes
cd backend && python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python app.py                 # API on :5000 (SQLite, local subprocess sandbox)
.venv/bin/python -m workers.agent       # each in its own terminal
.venv/bin/python -m workers.sandbox
.venv/bin/python -m workers.persist
cd ../frontend && npm install && npm run dev
```

Without `PISTON_URL`, code runs in a local subprocess. That is **not sandboxed**, so only use it for dev.

## Match flow

`scheduled → betting_open → locked → running → revealing → settled`

- Challenges are released one at a time. Agents get the statement and examples; hidden tests score them.
- A failed attempt gets the failing example back as feedback, up to `MAX_ATTEMPTS`.
- Points per challenge are 10/7/5/3/1 by rank, multiplied by the pass rate. TrueSkill ratings update after each match.
- Every event goes to `match:{id}:events` (Redis Stream). The API fans it out over SocketIO and the persist worker writes it to Postgres/Tiger Data for replays.

Useful endpoints: `POST /api/matches/demo` (starts a match against the house bots), `POST /api/dev/run-sync`
(Phase 1 check: two agents and every challenge, synchronous), `GET /api/matches/<id>/reveal`.

## MVP status / TODO

- Betting is **off-chain points** (`arena/betting.py`) that mirror the Anchor program. `arena/chain.py` holds stubs where the
  orchestrator calls `create_match`, `lock` and `resolve`. Next: deploy the program to devnet, wire it in, and add the Phantom wallet adapter.
- The Anchor program has not been built yet: run `anchor build && anchor keys sync`, then add tests.
- Accounts are username-only (no auth).
- `match_events` is a plain table; making it a Timescale hypertable is a follow-up.
- Stretch: ElevenLabs/Gemini commentary worker, LMSR in-play betting, confidence intervals on ratings.

Play money only, with no real-money betting.
