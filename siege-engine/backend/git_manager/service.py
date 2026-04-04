import json
import logging
from pathlib import Path

from git import Repo

from backend.config import settings

logger = logging.getLogger(__name__)


class GitManager:
    def __init__(self, base_path: str | None = None):
        self.base_path = Path(base_path or settings.git_repos_base_path)

    def init_repo(self, project_id: str) -> str:
        repo_path = self.base_path / project_id
        repo_path.mkdir(parents=True, exist_ok=True)
        Repo.init(repo_path)
        return str(repo_path)

    def commit_artifact(
        self,
        project_id: str,
        content: str,
        file_path: str,
        message: str | None = None,
    ) -> str:
        repo = self._get_repo(project_id)
        abs_path = Path(repo.working_dir) / file_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding="utf-8")
        repo.index.add([file_path])

        # If the file content is unchanged, skip the commit and return
        # the SHA of the most recent commit that touched this file.
        # Empty commits break file-based history lookups (iter_commits
        # skips them) which causes stale diffs.
        if not repo.index.diff("HEAD", paths=[file_path]):
            commits = list(repo.iter_commits(paths=file_path, max_count=1))
            if commits:
                return commits[0].hexsha

        commit = repo.index.commit(message or f"Update {file_path}")
        return commit.hexsha

    def get_diff(
        self,
        project_id: str,
        commit_sha_old: str,
        commit_sha_new: str,
        file_path: str | None = None,
    ) -> str:
        repo = self._get_repo(project_id)
        old = repo.commit(commit_sha_old)
        new = repo.commit(commit_sha_new)
        if file_path:
            diffs = old.diff(new, paths=[file_path], create_patch=True)
        else:
            diffs = old.diff(new, create_patch=True)
        parts: list[str] = []
        for d in diffs:
            raw = d.diff
            if isinstance(raw, bytes):
                parts.append(raw.decode("utf-8"))
            elif isinstance(raw, str):
                parts.append(raw)
        return "\n".join(parts)

    def get_file_history(self, project_id: str, file_path: str) -> list[dict]:
        repo = self._get_repo(project_id)
        commits = list(repo.iter_commits(paths=file_path))
        return [
            {
                "sha": c.hexsha,
                "message": c.message.strip(),
                "timestamp": c.committed_datetime.isoformat(),
            }
            for c in commits
        ]

    def get_file_at_version(self, project_id: str, file_path: str, commit_sha: str) -> str:
        repo = self._get_repo(project_id)
        commit = repo.commit(commit_sha)
        blob = commit.tree / file_path
        return blob.data_stream.read().decode("utf-8")

    def add_remote(self, project_id: str, remote_url: str, name: str = "origin"):
        repo = self._get_repo(project_id)
        try:
            repo.create_remote(name, remote_url)
        except Exception:
            # Remote may already exist
            repo.remote(name).set_url(remote_url)

    def push_branch(
        self,
        project_id: str,
        branch_name: str,
        remote: str = "origin",
        auth_url: str | None = None,
    ) -> str:
        repo = self._get_repo(project_id)
        # Create branch at HEAD without checkout
        if branch_name not in [b.name for b in repo.branches]:
            repo.create_head(branch_name)
        # Push using refspec (no checkout needed)
        # If auth_url provided, use it directly as push target so token
        # never persists in .git/config
        push_target = auth_url or remote
        result = repo.git.push(push_target, f"{branch_name}:{branch_name}")
        return str(result or "pushed")

    def pull_remote(self, project_id: str, branch: str = "main", remote: str = "origin") -> bool:
        """Pull from remote. Returns True if successful, False if conflicts."""
        repo = self._get_repo(project_id)
        remote_obj = repo.remote(remote)
        remote_obj.fetch()
        try:
            repo.git.merge(f"{remote}/{branch}")
            return True
        except Exception:
            return False

    def get_conflict_files(self, project_id: str) -> list[str]:
        repo = self._get_repo(project_id)
        # Unmerged entries indicate conflicts
        unmerged = repo.index.unmerged_blobs()
        return [str(k) for k in unmerged.keys()]  # type: ignore[arg-type]

    def resolve_conflict(self, project_id: str, file_path: str, content: str):
        repo = self._get_repo(project_id)
        abs_path = Path(repo.working_dir) / file_path
        abs_path.write_text(content, encoding="utf-8")
        repo.index.add([file_path])

    def get_current_branch(self, project_id: str) -> str:
        repo = self._get_repo(project_id)
        return repo.active_branch.name

    def checkpoint_run(
        self,
        project_id: str,
        siege_state: dict,
        message: str,
    ) -> str:
        """Write siege-state.json, stage all working tree changes, and commit.

        Individual artifacts are already committed during generation via
        commit_artifact(), so this checkpoint commit captures the JSON manifest
        plus any remaining uncommitted changes.  The resulting commit SHA
        represents the complete repo state at the end of the run.
        """
        repo = self._get_repo(project_id)
        manifest_path = Path(repo.working_dir) / "siege-state.json"
        manifest_path.write_text(json.dumps(siege_state, indent=2), encoding="utf-8")
        # Stage everything — manifest + any stragglers
        repo.git.add(A=True)
        commit = repo.index.commit(message)
        logger.info(
            "Checkpoint commit %s for project %s: %s",
            commit.hexsha[:8],
            project_id,
            message,
        )
        return commit.hexsha

    def get_file_at_commit(self, project_id: str, file_path: str, commit_sha: str) -> str:
        """Read a file from a specific commit (wrapper around get_file_at_version)."""
        return self.get_file_at_version(project_id, file_path, commit_sha)

    def push_current_branch(
        self,
        project_id: str,
        remote: str = "origin",
        auth_url: str | None = None,
    ) -> str:
        """Push the current branch (HEAD) to the remote."""
        repo = self._get_repo(project_id)
        try:
            branch_name = repo.active_branch.name
        except TypeError:
            branch_name = "main"
        push_target = auth_url or remote
        result = repo.git.push(push_target, f"{branch_name}:{branch_name}")
        return str(result or "pushed")

    def delete_repo(self, project_id: str):
        import shutil

        repo_path = self.base_path / project_id
        if repo_path.exists():
            shutil.rmtree(repo_path)

    def _get_repo(self, project_id: str) -> Repo:
        return Repo(self.base_path / project_id)


git_manager = GitManager()
