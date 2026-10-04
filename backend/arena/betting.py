"""Off-chain parimutuel pool using play-money points.

Mirrors the Anchor program in solana/ so the betting flow works before the
on-chain program is deployed. Swap these calls for chain.py when it is.
"""
from sqlalchemy import func

from .db import Bet, User


class BetError(Exception):
    pass


def pool(session, match_id):
    rows = (session.query(Bet.agent_id, func.sum(Bet.amount))
            .filter(Bet.match_id == match_id).group_by(Bet.agent_id).all())
    by_agent = {str(aid): int(total) for aid, total in rows}
    return {"by_agent": by_agent, "total": sum(by_agent.values())}


def place_bet(session, match, user_id, agent_id, amount):
    if match.stage != "betting_open":
        raise BetError("betting is closed")
    if agent_id not in match.agent_ids:
        raise BetError("agent is not in this match")
    if amount <= 0:
        raise BetError("amount must be positive")
    user = session.get(User, user_id)
    if user is None:
        raise BetError("unknown user")
    if user.points < amount:
        raise BetError("not enough points")
    user.points -= amount
    session.add(Bet(match_id=match.id, user_id=user_id, agent_id=agent_id, amount=amount))
    session.commit()
    return user


def settle(session, match_id, winner_agent_id):
    """Winners split the whole pool pro rata; refund everyone if nobody backed the winner."""
    bets = session.query(Bet).filter(Bet.match_id == match_id).all()
    total = sum(b.amount for b in bets)
    winning = sum(b.amount for b in bets if b.agent_id == winner_agent_id)
    for b in bets:
        if winning == 0:
            b.payout = b.amount
        else:
            b.payout = b.amount * total // winning if b.agent_id == winner_agent_id else 0
        if b.payout:
            session.get(User, b.user_id).points += b.payout
    session.commit()
