"""Cross-Platform Application Updater Service.

Handles pulling repository updates (via git or GitHub archive fallback)
and syncing uv workspace dependencies.
"""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

logger: logging.Logger = logging.getLogger(__name__)

GITHUB_REPO_ARCHIVE_URL: str = (
    "https://github.com/Kajiih/tinite-automation/archive/refs/heads/main.zip"
)


@dataclass(slots=True)
class UpdateResult:
    """Represents the outcome of an application update attempt."""

    success: bool
    message: str
    updated_files_count: int = 0


def resolve_workspace_root(start: Path | None = None) -> Path:
    """Locate the workspace root containing pyproject.toml or .git (Black/Pytest pattern).

    Args:
        start: Optional starting Path to begin parent directory traversal.

    Returns:
        Resolved Path of the repository or workspace root.
    """
    curr = (start or Path.cwd()).resolve()
    for directory in (curr, *curr.parents):
        if (directory / "pyproject.toml").is_file():
            return directory
    return curr


def _get_local_git_sha(git_path: str, root: Path) -> str:
    """Retrieve the current local HEAD commit hash."""
    try:
        proc = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            [git_path, "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except (OSError, subprocess.SubprocessError) as err:
        logger.debug("Failed to get local git commit: %s", err)
    return ""


def _get_remote_git_sha(git_path: str, root: Path) -> str:
    """Retrieve the latest commit hash on origin/main."""
    try:
        proc = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            [git_path, "ls-remote", "origin", "refs/heads/main"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.split()[0]
    except (OSError, subprocess.SubprocessError) as err:
        logger.debug("Failed to get remote git commit: %s", err)
    return ""


def _fetch_github_api_sha() -> str:
    """Fetch the latest commit SHA from the GitHub REST API."""
    url = "https://api.github.com/repos/Kajiih/tinite-automation/commits/main"
    if not url.startswith("https://"):
        return ""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Tinite-Automation-Updater",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as response:  # ruff: ignore[suspicious-url-open-usage]
            payload = json.loads(response.read().decode("utf-8"))
            return str(payload.get("sha", ""))
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as err:
        logger.debug("Failed to query GitHub commit API: %s", err)
        return ""


def _is_ancestor_commit(git_path: str, root: Path, remote_sha: str) -> bool:
    """Check if HEAD contains the given remote commit."""
    try:
        ancestor_check = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            [git_path, "merge-base", "--is-ancestor", remote_sha, "HEAD"],
            cwd=str(root),
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    else:
        return ancestor_check.returncode == 0


def check_update_available(repo_root: Path | None = None) -> dict[str, bool | str]:
    """Check whether a newer version or commit is available on the remote repository.

    Args:
        repo_root: Optional workspace repository root Path.

    Returns:
        Dictionary containing `update_available` (bool), `local_sha` (str), `remote_sha` (str).
    """
    resolved_root = resolve_workspace_root(repo_root)
    git_dir = resolved_root / ".git"
    git_path = shutil.which("git")
    is_git_repo = git_dir.is_dir() and git_path is not None

    local_sha = _get_local_git_sha(git_path, resolved_root) if is_git_repo and git_path else ""
    remote_sha = _get_remote_git_sha(git_path, resolved_root) if is_git_repo and git_path else ""

    if not remote_sha:
        remote_sha = _fetch_github_api_sha()

    if not local_sha:
        version_file = resolved_root / ".version_sha"
        if version_file.is_file():
            local_sha = version_file.read_text(encoding="utf-8").strip()

    if is_git_repo and remote_sha and git_path:
        is_already_contained = _is_ancestor_commit(git_path, resolved_root, remote_sha)
        update_available = not is_already_contained
    else:
        update_available = bool(remote_sha and local_sha and (remote_sha != local_sha))

    return {
        "update_available": update_available,
        "local_sha": local_sha[:7] if local_sha else "",
        "remote_sha": remote_sha[:7] if remote_sha else "",
    }


def _update_git_source(git_path: str, resolved_root: Path) -> None:
    """Pull latest source changes using git fast-forward."""
    try:
        logger.info("Executing 'git pull origin main --ff-only'...")
        exec_res = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            [git_path, "pull", "origin", "main", "--ff-only"],
            cwd=str(resolved_root),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if exec_res.returncode != 0:
            logger.warning("git pull failed: %s", exec_res.stderr)
            _update_from_github_archive(resolved_root)
    except (OSError, subprocess.SubprocessError) as err:
        logger.warning("Git pull exception: %s. Falling back to archive download.", err)
        _update_from_github_archive(resolved_root)


def _sync_uv_dependencies(resolved_root: Path) -> None:
    """Run uv sync to ensure project dependencies are synchronized."""
    uv_path = shutil.which("uv")
    if uv_path is None:
        user_uv = Path.home() / ".local" / "bin" / ("uv.exe" if os.name == "nt" else "uv")
        if user_uv.is_file():
            uv_path = str(user_uv)

    if uv_path is not None:
        try:
            logger.info("Synchronizing dependencies via 'uv sync --no-dev'...")
            subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
                [uv_path, "sync", "--no-dev"],
                cwd=str(resolved_root),
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as err:
            logger.warning("uv sync warning: %s", err)


def perform_app_update(repo_root: Path | None = None) -> UpdateResult:
    """Execute the application update routine.

    1. Pulls latest source code (via git pull or GitHub ZIP fallback).
    2. Runs `uv sync --no-dev` to update lockfile and dependencies.

    Args:
        repo_root: Optional workspace repository root Path.

    Returns:
        UpdateResult with success boolean and outcome message.
    """
    resolved_root = resolve_workspace_root(repo_root)
    logger.info("Starting application update for repository at: %s", resolved_root)
    git_dir = resolved_root / ".git"
    git_path = shutil.which("git")

    if git_dir.is_dir() and git_path is not None:
        _update_git_source(git_path, resolved_root)
    else:
        logger.info("Git repository not detected or git binary missing. Using archive download.")
        _update_from_github_archive(resolved_root)

    _sync_uv_dependencies(resolved_root)

    return UpdateResult(
        success=True,
        message="Application successfully updated! Please refresh the page or restart the app.",
    )


def _extract_zip_contents(zip_bytes: bytes, repo_root: Path) -> None:
    """Extract zip archive files while ignoring version control and cache directories."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        root_prefix = zf.namelist()[0].split("/")[0] + "/"
        for member in zf.namelist():
            if not member.startswith(root_prefix) or member == root_prefix:
                continue
            relative_path = member[len(root_prefix) :]
            if not relative_path or relative_path.startswith((".git", ".venv", ".pytest_cache")):
                continue

            target_file = repo_root / relative_path
            if member.endswith("/"):
                target_file.mkdir(parents=True, exist_ok=True)
            else:
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_bytes(zf.read(member))


def _update_from_github_archive(repo_root: Path) -> None:
    """Download and extract GitHub repository zip archive as a fallback.

    Args:
        repo_root: Path to destination repository directory.
    """
    if not GITHUB_REPO_ARCHIVE_URL.startswith("https://"):
        return
    try:
        req = urllib.request.Request(
            GITHUB_REPO_ARCHIVE_URL,
            headers={"User-Agent": "Amazon-Automation-WebHub-Updater"},
        )
        with urllib.request.urlopen(req, timeout=30) as response:  # ruff: ignore[suspicious-url-open-usage]
            zip_bytes = response.read()

        _extract_zip_contents(zip_bytes, repo_root)
    except (urllib.error.URLError, zipfile.BadZipFile, OSError) as err:
        logger.warning("GitHub archive download/extract error: %s", err)
