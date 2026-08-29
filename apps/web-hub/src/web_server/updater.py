"""Cross-Platform Application Updater Service.

Handles pulling repository updates (via git or GitHub archive fallback)
and syncing uv workspace dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
import io
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import urllib.error
import urllib.request
import zipfile

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
    """Locate the workspace root containing pyproject.toml or .git (Black/Pytest pattern)."""
    curr = (start or Path.cwd()).resolve()
    for directory in (curr, *curr.parents):
        if (directory / "pyproject.toml").is_file():
            return directory
    return curr


def check_update_available(repo_root: Path | None = None) -> dict[str, bool | str]:
    """Check whether a newer version or commit is available on the remote repository."""
    resolved_root = resolve_workspace_root(repo_root)
    git_dir = resolved_root / ".git"

    local_sha = ""
    remote_sha = ""
    is_git_repo = git_dir.is_dir() and shutil.which("git") is not None

    # Check via git CLI
    if is_git_repo:
        try:
            local_proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(resolved_root),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if local_proc.returncode == 0:
                local_sha = local_proc.stdout.strip()
        except Exception as err:
            logger.debug("Failed to get local git commit: %s", err)

        try:
            remote_proc = subprocess.run(
                ["git", "ls-remote", "origin", "refs/heads/main"],
                cwd=str(resolved_root),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if remote_proc.returncode == 0 and remote_proc.stdout.strip():
                remote_sha = remote_proc.stdout.split()[0]
        except Exception as err:
            logger.debug("Failed to get remote git commit: %s", err)

    # Check via GitHub API fallback
    if not remote_sha:
        try:
            req = urllib.request.Request(
                "https://api.github.com/repos/Kajiih/tinite-automation/commits/main",
                headers={
                    "User-Agent": "Tinite-Automation-Updater",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                remote_sha = payload.get("sha", "")
        except Exception as err:
            logger.debug("Failed to query GitHub commit API: %s", err)

    if not local_sha:
        version_file = resolved_root / ".version_sha"
        if version_file.is_file():
            local_sha = version_file.read_text(encoding="utf-8").strip()

    if is_git_repo and remote_sha:
        # Check if local repo already contains the remote commit
        try:
            ancestor_check = subprocess.run(
                ["git", "merge-base", "--is-ancestor", remote_sha, "HEAD"],
                cwd=str(resolved_root),
                capture_output=True,
                timeout=5,
            )
            # returncode 0 = HEAD is ahead of or equal to remote_sha (no update needed)
            update_available = ancestor_check.returncode != 0
        except Exception:
            update_available = False
    else:
        update_available = bool(remote_sha and local_sha and (remote_sha != local_sha))

    return {
        "update_available": update_available,
        "local_sha": local_sha[:7] if local_sha else "",
        "remote_sha": remote_sha[:7] if remote_sha else "",
    }


def perform_app_update(repo_root: Path | None = None) -> UpdateResult:
    """Executes the application update routine:
    1. Pulls latest source code (via git pull or GitHub ZIP fallback).
    2. Runs `uv sync --no-dev` to update lockfile and dependencies.
    """
    resolved_root = resolve_workspace_root(repo_root)
    logger.info("Starting application update for repository at: %s", resolved_root)
    git_dir = resolved_root / ".git"

    # Step 1: Update source code
    if git_dir.is_dir() and shutil.which("git") is not None:
        try:
            logger.info("Executing 'git pull origin main --ff-only'...")
            exec_res = subprocess.run(
                ["git", "pull", "origin", "main", "--ff-only"],
                cwd=str(resolved_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if exec_res.returncode != 0:
                logger.warning("git pull failed: %s", exec_res.stderr)
                # Fallback to archive download if git pull fails
                _update_from_github_archive(resolved_root)
        except Exception as err:
            logger.warning("Git pull exception: %s. Falling back to archive download.", err)
            _update_from_github_archive(resolved_root)
    else:
        logger.info("Git repository not detected or git binary missing. Using archive download.")
        _update_from_github_archive(resolved_root)

    # Step 2: Synchronize dependencies with uv
    uv_path = shutil.which("uv")
    if uv_path is None:
        user_uv = Path.home() / ".local" / "bin" / ("uv.exe" if os.name == "nt" else "uv")
        if user_uv.is_file():
            uv_path = str(user_uv)

    if uv_path is not None:
        try:
            logger.info("Synchronizing dependencies via 'uv sync --no-dev'...")
            subprocess.run(
                [uv_path, "sync", "--no-dev"],
                cwd=str(resolved_root),
                capture_output=True,
                text=True,
                timeout=60,
            )
        except Exception as err:
            logger.warning("uv sync warning: %s", err)

    return UpdateResult(
        success=True,
        message="Application successfully updated! Please refresh the page or restart the app.",
    )


def _update_from_github_archive(repo_root: Path) -> None:
    """Download and extract GitHub repository zip archive as a fallback."""
    try:
        req = urllib.request.Request(
            GITHUB_REPO_ARCHIVE_URL,
            headers={"User-Agent": "Amazon-Automation-WebHub-Updater"},
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            zip_bytes = response.read()

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            root_prefix = zf.namelist()[0].split("/")[0] + "/"
            for member in zf.namelist():
                if not member.startswith(root_prefix) or member == root_prefix:
                    continue
                relative_path = member[len(root_prefix) :]
                if not relative_path or relative_path.startswith((
                    ".git",
                    ".venv",
                    ".pytest_cache",
                )):
                    continue

                target_file = repo_root / relative_path
                if member.endswith("/"):
                    target_file.mkdir(parents=True, exist_ok=True)
                else:
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    target_file.write_bytes(zf.read(member))
    except urllib.error.HTTPError as err:
        logger.warning("GitHub archive download returned HTTP %d: %s", err.code, err.reason)
    except Exception as err:
        logger.warning("Could not download GitHub archive: %s", err)
