"""Challenge loading and the commit-reveal hash of a challenge set."""
import hashlib
import json
import random
import secrets
from functools import lru_cache
from pathlib import Path

CHALLENGE_DIR = Path(__file__).resolve().parent.parent / "challenges"


@lru_cache(maxsize=1)
def load_all():
    out = {}
    for path in sorted(CHALLENGE_DIR.glob("*.json")):
        ch = json.loads(path.read_text())
        out[ch["id"]] = ch
    return out


def get(challenge_id):
    return load_all()[challenge_id]


def pick(n):
    ids = list(load_all())
    random.shuffle(ids)
    return ids[:n]


def public_view(ch):
    """What agents and spectators see before the reveal: no hidden tests."""
    return {k: ch[k] for k in ("id", "title", "statement", "examples", "time_limit_s", "languages")}


def commit(challenge_ids):
    """Return (payload, sha256 hex). The payload is revealed after the match."""
    payload = json.dumps(
        {
            "salt": secrets.token_hex(16),
            "challenges": [
                {k: get(cid)[k] for k in ("id", "title", "statement", "examples", "hidden_tests")}
                for cid in challenge_ids
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return payload, hashlib.sha256(payload.encode()).hexdigest()
