"""SQLAlchemy ORM models — mirrors docs/05_DATA_MODEL.md §3.

Only the tables needed by the current runtime are materialized here. Extra tables
(evaluation scenarios, metric definitions) live in JSON-on-disk for
reproducibility and so the evaluation harness stays runnable offline.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    intent: Mapped[str] = mapped_column(Text, nullable=False)
    tone: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_body: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)

    facts: Mapped[list[DraftKeyFact]] = relationship(
        back_populates="draft", cascade="all, delete-orphan", order_by="DraftKeyFact.sort_order"
    )
    revisions: Mapped[list[DraftRevision]] = relationship(
        back_populates="draft", cascade="all, delete-orphan", order_by="DraftRevision.created_at"
    )


class DraftKeyFact(Base):
    __tablename__ = "draft_key_facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    draft_id: Mapped[str] = mapped_column(
        ForeignKey("drafts.id", ondelete="CASCADE"), nullable=False
    )
    fact_text: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    draft: Mapped[Draft] = relationship(back_populates="facts")


class DraftRevision(Base):
    __tablename__ = "draft_revisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    draft_id: Mapped[str] = mapped_column(
        ForeignKey("drafts.id", ondelete="CASCADE"), nullable=False
    )
    revision_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    subject_suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)

    draft: Mapped[Draft] = relationship(back_populates="revisions")


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_name: Mapped[str] = mapped_column(String(200), nullable=False)
    scenario_set_id: Mapped[str] = mapped_column(String(64), nullable=False)
    config_a_json: Mapped[str] = mapped_column(Text, nullable=False)
    config_b_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)
