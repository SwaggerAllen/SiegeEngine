"""Tests for ComponentManagerMixin.reparse_fanout."""

import json
import uuid

import pytest

from backend.models import (
    Artifact,
    ArtifactStatus,
    ArtifactType,
    ComponentDefinition,
)
from backend.pipeline.engine import PipelineEngine


def _id():
    return str(uuid.uuid4())


def _make_component_map_content(components: list[dict]) -> str:
    """Build artifact content with a ```components code block."""
    return f"```components\n{json.dumps(components)}\n```"


def _make_sub_component_map_content(
    sub_components: list[dict], needs_decomposition: bool = True
) -> str:
    data = {
        "needs_decomposition": needs_decomposition,
        "components": sub_components,
    }
    return f"```components\n{json.dumps(data)}\n```"


def _make_component_map(db, project_id, content, *, component_key=None):
    art = Artifact(
        id=_id(),
        project_id=project_id,
        artifact_type=ArtifactType.COMPONENT_MAP,
        name="Component Extraction",
        component_key=component_key,
        content=content,
        status=ArtifactStatus.APPROVED,
        version=1,
    )
    db.add(art)
    db.flush()
    return art


def _make_sub_component_map(db, project_id, parent_key, content):
    art = Artifact(
        id=_id(),
        project_id=project_id,
        artifact_type=ArtifactType.SUB_COMPONENT_MAP,
        name=f"Sub-Component Extraction - {parent_key}",
        component_key=parent_key,
        content=content,
        status=ArtifactStatus.APPROVED,
        version=1,
    )
    db.add(art)
    db.flush()
    return art


def _add_component_def(db, project_id, key, *, parent_key=None, dependencies=None):
    cd = ComponentDefinition(
        project_id=project_id,
        key=key,
        name=key.replace("_", " ").title(),
        parent_key=parent_key,
        dependencies=dependencies or [],
    )
    db.add(cd)
    db.flush()
    return cd


def _get_component_keys(db, project_id, *, parent_key=None):
    q = db.query(ComponentDefinition).filter_by(project_id=project_id)
    if parent_key is None:
        q = q.filter(ComponentDefinition.parent_key.is_(None))
    else:
        q = q.filter_by(parent_key=parent_key)
    return {d.key for d in q.all()}


def _get_component_deps(db, project_id, key, *, parent_key=None):
    q = db.query(ComponentDefinition).filter_by(project_id=project_id, key=key)
    if parent_key is None:
        q = q.filter(ComponentDefinition.parent_key.is_(None))
    else:
        q = q.filter_by(parent_key=parent_key)
    cd = q.first()
    return sorted(cd.dependencies or []) if cd else None


class TestReparseFanoutValidation:
    """Error cases and input validation."""

    def test_raises_for_missing_artifact(self, db, project):
        engine = PipelineEngine(db)
        with pytest.raises(ValueError, match="Artifact not found"):
            engine.reparse_fanout(project.id, "nonexistent-id")

    def test_raises_for_wrong_project(self, db, project):
        other_project_id = _id()
        content = _make_component_map_content([{"key": "a", "name": "A"}])
        art = _make_component_map(db, other_project_id, content)
        engine = PipelineEngine(db)
        with pytest.raises(ValueError, match="does not belong"):
            engine.reparse_fanout(project.id, art.id)

    def test_raises_for_empty_content(self, db, project):
        art = Artifact(
            id=_id(),
            project_id=project.id,
            artifact_type=ArtifactType.COMPONENT_MAP,
            name="Empty",
            content=None,
            status=ArtifactStatus.APPROVED,
            version=1,
        )
        db.add(art)
        db.flush()
        engine = PipelineEngine(db)
        with pytest.raises(ValueError, match="no content"):
            engine.reparse_fanout(project.id, art.id)

    def test_raises_for_non_fanout_artifact(self, db, project):
        art = Artifact(
            id=_id(),
            project_id=project.id,
            artifact_type=ArtifactType.SYSTEM_ARCHITECTURE,
            name="Architecture",
            content="some content",
            status=ArtifactStatus.APPROVED,
            version=1,
        )
        db.add(art)
        db.flush()
        engine = PipelineEngine(db)
        with pytest.raises(ValueError, match="not a fanout artifact"):
            engine.reparse_fanout(project.id, art.id)

    def test_raises_for_sub_component_map_without_component_key(self, db, project):
        art = Artifact(
            id=_id(),
            project_id=project.id,
            artifact_type=ArtifactType.SUB_COMPONENT_MAP,
            name="Sub-Comp Map",
            component_key=None,
            content="some content",
            status=ArtifactStatus.APPROVED,
            version=1,
        )
        db.add(art)
        db.flush()
        engine = PipelineEngine(db)
        with pytest.raises(ValueError, match="no component_key"):
            engine.reparse_fanout(project.id, art.id)


class TestReparseFanoutComponentMap:
    """Tests for reparse_fanout with COMPONENT_MAP artifacts."""

    def test_adds_new_components(self, db, project):
        content = _make_component_map_content([
            {"key": "auth", "name": "Auth", "dependencies": []},
            {"key": "api", "name": "API", "dependencies": ["auth"]},
        ])
        art = _make_component_map(db, project.id, content)
        engine = PipelineEngine(db)

        result = engine.reparse_fanout(project.id, art.id)

        assert set(result["added"]) == {"auth", "api"}
        assert result["removed"] == []
        assert result["updated"] == []
        assert result["total"] == 2
        assert _get_component_keys(db, project.id) == {"auth", "api"}

    def test_removes_orphaned_components(self, db, project):
        _add_component_def(db, project.id, "auth")
        _add_component_def(db, project.id, "old_module")

        content = _make_component_map_content([
            {"key": "auth", "name": "Auth", "dependencies": []},
        ])
        art = _make_component_map(db, project.id, content)
        engine = PipelineEngine(db)

        result = engine.reparse_fanout(project.id, art.id)

        assert result["added"] == []
        assert result["removed"] == ["old_module"]
        assert result["total"] == 1
        assert _get_component_keys(db, project.id) == {"auth"}

    def test_no_changes_when_components_match(self, db, project):
        _add_component_def(db, project.id, "auth", dependencies=["db"])
        _add_component_def(db, project.id, "db")

        content = _make_component_map_content([
            {"key": "auth", "name": "Auth", "dependencies": ["db"]},
            {"key": "db", "name": "Database", "dependencies": []},
        ])
        art = _make_component_map(db, project.id, content)
        engine = PipelineEngine(db)

        result = engine.reparse_fanout(project.id, art.id)

        assert result["added"] == []
        assert result["removed"] == []
        assert result["updated"] == []
        assert result["total"] == 2

    def test_detects_updated_dependencies(self, db, project):
        _add_component_def(db, project.id, "auth", dependencies=[])
        _add_component_def(db, project.id, "api", dependencies=["auth"])
        _add_component_def(db, project.id, "db", dependencies=[])

        # Now auth depends on db, and api depends on both
        content = _make_component_map_content([
            {"key": "auth", "name": "Auth", "dependencies": ["db"]},
            {"key": "api", "name": "API", "dependencies": ["auth", "db"]},
            {"key": "db", "name": "Database", "dependencies": []},
        ])
        art = _make_component_map(db, project.id, content)
        engine = PipelineEngine(db)

        result = engine.reparse_fanout(project.id, art.id)

        assert result["added"] == []
        assert result["removed"] == []
        assert set(result["updated"]) == {"auth", "api"}
        assert result["total"] == 3
        # Verify dependencies were actually persisted
        assert _get_component_deps(db, project.id, "auth") == ["db"]
        assert _get_component_deps(db, project.id, "api") == ["auth", "db"]

    def test_simultaneous_add_remove_update(self, db, project):
        _add_component_def(db, project.id, "auth", dependencies=[])
        _add_component_def(db, project.id, "old_svc", dependencies=[])
        _add_component_def(db, project.id, "db", dependencies=[])

        content = _make_component_map_content([
            {"key": "auth", "name": "Auth", "dependencies": ["db"]},
            {"key": "db", "name": "Database", "dependencies": []},
            {"key": "new_svc", "name": "New Service", "dependencies": ["auth"]},
        ])
        art = _make_component_map(db, project.id, content)
        engine = PipelineEngine(db)

        result = engine.reparse_fanout(project.id, art.id)

        assert result["added"] == ["new_svc"]
        assert result["removed"] == ["old_svc"]
        assert result["updated"] == ["auth"]
        assert result["total"] == 3


class TestReparseFanoutSubComponentMap:
    """Tests for reparse_fanout with SUB_COMPONENT_MAP artifacts."""

    def test_adds_new_sub_components(self, db, project):
        _add_component_def(db, project.id, "auth")  # parent

        content = _make_sub_component_map_content([
            {"key": "tokens", "name": "Token Manager", "dependencies": []},
            {"key": "sessions", "name": "Session Manager", "dependencies": ["tokens"]},
        ])
        art = _make_sub_component_map(db, project.id, "auth", content)
        engine = PipelineEngine(db)

        result = engine.reparse_fanout(project.id, art.id)

        assert set(result["added"]) == {"tokens", "sessions"}
        assert result["removed"] == []
        assert result["total"] == 2
        assert _get_component_keys(db, project.id, parent_key="auth") == {"tokens", "sessions"}

    def test_removes_orphaned_sub_components(self, db, project):
        _add_component_def(db, project.id, "auth")
        _add_component_def(db, project.id, "tokens", parent_key="auth")
        _add_component_def(db, project.id, "old_sub", parent_key="auth")

        content = _make_sub_component_map_content([
            {"key": "tokens", "name": "Token Manager", "dependencies": []},
        ])
        art = _make_sub_component_map(db, project.id, "auth", content)
        engine = PipelineEngine(db)

        result = engine.reparse_fanout(project.id, art.id)

        assert result["removed"] == ["old_sub"]
        assert result["total"] == 1

    def test_detects_updated_sub_component_dependencies(self, db, project):
        _add_component_def(db, project.id, "auth")
        _add_component_def(db, project.id, "tokens", parent_key="auth", dependencies=[])
        _add_component_def(db, project.id, "sessions", parent_key="auth", dependencies=[])

        content = _make_sub_component_map_content([
            {"key": "tokens", "name": "Token Manager", "dependencies": []},
            {"key": "sessions", "name": "Session Manager", "dependencies": ["tokens"]},
        ])
        art = _make_sub_component_map(db, project.id, "auth", content)
        engine = PipelineEngine(db)

        result = engine.reparse_fanout(project.id, art.id)

        assert result["added"] == []
        assert result["removed"] == []
        assert result["updated"] == ["sessions"]
        assert _get_component_deps(db, project.id, "sessions", parent_key="auth") == ["tokens"]

    def test_no_changes_when_not_needs_decomposition(self, db, project):
        _add_component_def(db, project.id, "auth")
        _add_component_def(db, project.id, "tokens", parent_key="auth")

        content = _make_sub_component_map_content([], needs_decomposition=False)
        art = _make_sub_component_map(db, project.id, "auth", content)
        engine = PipelineEngine(db)

        result = engine.reparse_fanout(project.id, art.id)

        # _store_sub_components returns early when needs_decomposition=False,
        # so existing sub-components remain unchanged
        assert result["added"] == []
        assert result["removed"] == []
        assert result["total"] == 1

    def test_does_not_affect_other_parents(self, db, project):
        """Reparsing sub-components for one parent must not touch another's."""
        _add_component_def(db, project.id, "auth")
        _add_component_def(db, project.id, "api")
        _add_component_def(db, project.id, "tokens", parent_key="auth")
        _add_component_def(db, project.id, "routes", parent_key="api")

        content = _make_sub_component_map_content([
            {"key": "tokens", "name": "Tokens", "dependencies": []},
            {"key": "oauth", "name": "OAuth", "dependencies": ["tokens"]},
        ])
        art = _make_sub_component_map(db, project.id, "auth", content)
        engine = PipelineEngine(db)

        result = engine.reparse_fanout(project.id, art.id)

        assert result["added"] == ["oauth"]
        # api's sub-components untouched
        assert _get_component_keys(db, project.id, parent_key="api") == {"routes"}
