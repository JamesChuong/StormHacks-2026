from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, scoped_session, sessionmaker

from . import config

engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
Session = scoped_session(sessionmaker(engine, expire_on_commit=False))


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True)
    points: Mapped[int] = mapped_column(Integer, default=config.STARTING_POINTS)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    def to_dict(self):
        return {"id": self.id, "username": self.username, "points": self.points}


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(60))
    model: Mapped[str] = mapped_column(String(60))
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    # [{"name": ..., "instructions": ...}]
    skills: Mapped[list] = mapped_column(JSON, default=list)
    mu: Mapped[float] = mapped_column(Float, default=25.0)
    sigma: Mapped[float] = mapped_column(Float, default=25.0 / 3)
    matches_played: Mapped[int] = mapped_column(Integer, default=0)

    def to_dict(self):
        return {
            "id": self.id, "user_id": self.user_id, "name": self.name, "model": self.model,
            "system_prompt": self.system_prompt, "skills": self.skills,
            "mu": round(self.mu, 2), "sigma": round(self.sigma, 2),
            "rating": round(self.mu - 3 * self.sigma, 2),
            "matches_played": self.matches_played,
        }


class Match(Base):
    __tablename__ = "matches"
    id: Mapped[int] = mapped_column(primary_key=True)
    stage: Mapped[str] = mapped_column(String(20), default="scheduled")
    agent_ids: Mapped[list] = mapped_column(JSON)
    challenge_ids: Mapped[list] = mapped_column(JSON)
    commit_hash: Mapped[str] = mapped_column(String(64))
    # Secret until the revealing stage.
    reveal_payload: Mapped[str] = mapped_column(Text)
    winner_agent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def to_dict(self):
        return {
            "id": self.id, "stage": self.stage, "agent_ids": self.agent_ids,
            "commit_hash": self.commit_hash, "winner_agent_id": self.winner_agent_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class MatchResult(Base):
    __tablename__ = "match_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    points: Mapped[float] = mapped_column(Float)
    rank: Mapped[int] = mapped_column(Integer)


class Bet(Base):
    __tablename__ = "bets"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    amount: Mapped[int] = mapped_column(Integer)
    payout: Mapped[int | None] = mapped_column(Integer, nullable=True)


class MatchEvent(Base):
    """Event timeline for replays (Tiger Data / TimescaleDB in Docker)."""
    __tablename__ = "match_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(Integer, index=True)
    stream_id: Mapped[str] = mapped_column(String(32))
    type: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict] = mapped_column(JSON)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def init_db():
    Base.metadata.create_all(engine)
