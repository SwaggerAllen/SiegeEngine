import httpx


class GitHubService:
    """GitHub API client using stored OAuth tokens."""

    BASE_URL = "https://api.github.com"

    def __init__(self, access_token: str):
        self.token = access_token
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def get_user(self) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.BASE_URL}/user", headers=self.headers)
            resp.raise_for_status()
            return resp.json()

    async def create_pr(
        self,
        repo_slug: str,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main",
    ) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.BASE_URL}/repos/{repo_slug}/pulls",
                headers=self.headers,
                json={
                    "title": title,
                    "body": body,
                    "head": head_branch,
                    "base": base_branch,
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def list_prs(self, repo_slug: str, state: str = "open") -> list[dict]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.BASE_URL}/repos/{repo_slug}/pulls",
                headers=self.headers,
                params={"state": state},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_pr_status(self, repo_slug: str, pr_number: int) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.BASE_URL}/repos/{repo_slug}/pulls/{pr_number}",
                headers=self.headers,
            )
            resp.raise_for_status()
            return resp.json()
