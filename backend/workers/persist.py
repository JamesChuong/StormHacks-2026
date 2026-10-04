"""Persist worker: copies every match event into the database for replays."""
import logging
import time
from datetime import datetime, timezone

from arena import bus
from arena.db import MatchEvent, Session

log = logging.getLogger("persist-worker")
GROUP = "persisters"
CONSUMER = "persist-1"


def drain(match_id):
    stream = bus.events_key(match_id)
    bus.ensure_group(stream, GROUP)
    resp = bus.r.xreadgroup(GROUP, CONSUMER, {stream: "0"}, count=500)  # pending first
    if not resp or not resp[0][1]:
        resp = bus.r.xreadgroup(GROUP, CONSUMER, {stream: ">"}, count=500)
    entries = resp[0][1] if resp else []
    if not entries:
        return False
    s = Session()
    done = False
    for event_id, fields in entries:
        ev = bus.decode_event(event_id, fields)
        s.add(MatchEvent(match_id=int(match_id), stream_id=event_id, type=ev["type"], data=ev["data"],
                         ts=datetime.fromtimestamp(ev["ts"], tz=timezone.utc)))
        done |= ev["type"] == "stage" and ev["data"]["stage"] in ("settled", "error")
    s.commit()
    bus.r.xack(stream, GROUP, *[eid for eid, _ in entries])
    if done:
        # Everything is persisted: let the hot Redis copy expire.
        bus.r.srem(bus.ACTIVE_MATCHES, match_id)
        for key in bus.r.keys(f"match:{match_id}:*"):
            bus.r.expire(key, 3600)
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    while True:
        busy = False
        for mid in bus.r.smembers(bus.ACTIVE_MATCHES):
            try:
                busy |= drain(mid)
            except Exception:
                log.exception("persisting match %s failed", mid)
                Session.rollback()
        if not busy:
            time.sleep(1)
