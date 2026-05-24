"""Project model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base

if TYPE_CHECKING:
    from backend.models.input_document import InputDocument


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    remote_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    github_repo_slug: Mapped[str | None] = mapped_column(String(200), nullable=True)
    git_repo_path: Mapped[str] = mapped_column(String(500), nullable=False)
    auto_push_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # ``"remote"`` (the GitHub-remote create flow) or ``"upload"`` (the
    # tarball-import create flow). Drives ``is_writable`` — uploads
    # have no remote to push to.
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="remote")
    # Free-form per-project preferences (generation timeouts, model
    # overrides, etc.). See backend.projects.settings for the typed
    # view and default values. ``None`` means "no overrides".
    settings: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    input_documents: Mapped[list["InputDocument"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    @property
    def is_writable(self) -> bool:
        """True for projects with a remote we can push to — i.e. not uploads."""
        return self.source == "remote"
