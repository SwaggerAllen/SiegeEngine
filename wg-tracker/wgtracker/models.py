"""SQLAlchemy ORM models.

Postgres-native: JSONB for flexible fields, real enums, foreign keys with
cascading behavior, and a generated tsvector + GIN index for thread full-text
search. Indexed on commonly-queried columns (working_group, last_activity_date,
topic_id, from_address).
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Computed,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ThreadStatus(str, enum.Enum):
    active = "active"
    concluded = "concluded"
    abandoned = "abandoned"


class ConsensusState(str, enum.Enum):
    clear_consensus = "clear_consensus"
    emerging_consensus = "emerging_consensus"
    active_debate = "active_debate"
    no_consensus = "no_consensus"
    single_voice = "single_voice"


class ProcessingStage(str, enum.Enum):
    ingestion = "ingestion"
    prefilter = "prefilter"
    draft_sync = "draft_sync"
    summarization = "summarization"
    categorization = "categorization"


# ---------------------------------------------------------------------------
# Core archive tables
# ---------------------------------------------------------------------------


class Thread(Base):
    __tablename__ = "threads"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject: Mapped[str] = mapped_column(Text, index=True)
    working_group: Mapped[str] = mapped_column(String(64), index=True)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    archive_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ThreadStatus | None] = mapped_column(
        Enum(ThreadStatus, name="thread_status")
    )
    summary: Mapped[str | None] = mapped_column(Text)
    key_positions: Mapped[list | None] = mapped_column(JSONB)  # [{position, holder, context}]
    consensus_state: Mapped[ConsensusState | None] = mapped_column(
        Enum(ConsensusState, name="consensus_state")
    )
    participants: Mapped[list | None] = mapped_column(JSONB)  # [email, ...]
    is_admin_only: Mapped[bool] = mapped_column(default=False)
    # Content fingerprint at time of last summary, used for idempotent re-summary.
    summary_source_fingerprint: Mapped[str | None] = mapped_column(String(64))
    last_processed: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Generated full-text column over subject + summary (Postgres-native FTS).
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', coalesce(subject,'') || ' ' || coalesce(summary,''))",
            persisted=True,
        ),
    )

    messages: Mapped[list[Message]] = relationship(
        back_populates="thread", cascade="all, delete-orphan"
    )
    topic_links: Mapped[list[ThreadTopic]] = relationship(
        back_populates="thread", cascade="all, delete-orphan"
    )
    draft_links: Mapped[list[ThreadDraft]] = relationship(
        back_populates="thread", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_threads_search_vector", "search_vector", postgresql_using="gin"),
        Index("ix_threads_wg_last_activity", "working_group", "last_activity_date"),
    )


class Message(Base):
    __tablename__ = "messages"

    message_id: Mapped[str] = mapped_column(String(512), primary_key=True)
    thread_id: Mapped[str | None] = mapped_column(
        ForeignKey("threads.thread_id", ondelete="CASCADE"), index=True
    )
    working_group: Mapped[str] = mapped_column(String(64), index=True)
    from_address: Mapped[str | None] = mapped_column(String(320), index=True)
    from_name: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(Text)
    date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archive_url: Mapped[str | None] = mapped_column(Text)
    body_cleaned: Mapped[str | None] = mapped_column(Text)
    body_original: Mapped[str | None] = mapped_column(Text)
    in_reply_to: Mapped[str | None] = mapped_column(String(512))
    references: Mapped[list | None] = mapped_column(JSONB)  # [message_id, ...]
    is_admin: Mapped[bool | None] = mapped_column()  # set by prefilter stage

    thread: Mapped[Thread | None] = relationship(back_populates="messages")


class Topic(Base):
    __tablename__ = "topics"

    topic_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[list | None] = mapped_column(JSONB)

    thread_links: Mapped[list[ThreadTopic]] = relationship(
        back_populates="topic", cascade="all, delete-orphan"
    )


class ThreadTopic(Base):
    __tablename__ = "thread_topics"

    thread_id: Mapped[str] = mapped_column(
        ForeignKey("threads.thread_id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("topics.topic_id", ondelete="CASCADE"), primary_key=True, index=True
    )
    confidence: Mapped[float | None] = mapped_column(Float)

    thread: Mapped[Thread] = relationship(back_populates="topic_links")
    topic: Mapped[Topic] = relationship(back_populates="thread_links")


class Draft(Base):
    __tablename__ = "drafts"

    draft_name: Mapped[str] = mapped_column(String(256), primary_key=True)
    current_version: Mapped[str | None] = mapped_column(String(16))
    title: Mapped[str | None] = mapped_column(Text)
    working_group: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str | None] = mapped_column(String(64))
    rfc_number: Mapped[str | None] = mapped_column(String(32))
    authors: Mapped[list | None] = mapped_column(JSONB)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    datatracker_url: Mapped[str | None] = mapped_column(Text)
    abstract: Mapped[str | None] = mapped_column(Text)
    versions: Mapped[list | None] = mapped_column(JSONB)  # [{version, date, url}]

    thread_links: Mapped[list[ThreadDraft]] = relationship(
        back_populates="draft", cascade="all, delete-orphan"
    )


class ThreadDraft(Base):
    __tablename__ = "thread_drafts"

    thread_id: Mapped[str] = mapped_column(
        ForeignKey("threads.thread_id", ondelete="CASCADE"), primary_key=True
    )
    draft_name: Mapped[str] = mapped_column(
        ForeignKey("drafts.draft_name", ondelete="CASCADE"), primary_key=True, index=True
    )
    versions_referenced: Mapped[list | None] = mapped_column(JSONB)
    first_referenced_in_thread: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    thread: Mapped[Thread] = relationship(back_populates="draft_links")
    draft: Mapped[Draft] = relationship(back_populates="thread_links")


class ProcessingLog(Base):
    __tablename__ = "processing_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    stage: Mapped[ProcessingStage] = mapped_column(Enum(ProcessingStage, name="processing_stage"))
    working_group: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(512))  # thread_id / message_id / batch_id
    status: Mapped[str] = mapped_column(String(32))  # ok / error / retry / skipped
    model: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    detail: Mapped[dict | None] = mapped_column(JSONB)  # errors, retries, free-form context

    __table_args__ = (Index("ix_processing_log_stage_date", "stage", "created_at"),)


# ---------------------------------------------------------------------------
# Auth tables (addendum: basic authenticated UI)
# ---------------------------------------------------------------------------


class UserRole(str, enum.Enum):
    admin = "admin"
    viewer = "viewer"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Which invite (if any) this account was created from.
    invite_token: Mapped[str | None] = mapped_column(String(64))


class Invite(Base):
    __tablename__ = "invites"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), default=UserRole.viewer)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    # Single-use by default: set when an account is created from this invite.
    used_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(default=False)
