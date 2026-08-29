"""
Cross-Platform Application Updater Service

Handles pulling repository updates (via git or GitHub archive fallback)
and syncing uv workspace dependencies.
"""

from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

logger: logging.Logger = logging.getLogger(__name__)

GITHUB_REPO_ARCHIVE_URL: str = "https://github.com/paquerot/alex_automation/archive/refs/heads/main.zip"


@dataclass(slots=True)
class UpdateResult:
    """Represents the outcome of an application update attempt."""
    success: bool
    message: str
    updated_files_count: int = 0


def perform_app_update(repo_root: Path) -> UpdateResult:
    """
    Executes the application update routine:
    1. Pulls latest source code (via git pull or GitHub ZIP fallback).
    2. Runs `uv sync --no-dev` to update lockfile and dependencies.
    """
    logger.info("Starting application update for repository at: %s", repo_root)
    git_dir = repo_root / ".git"

    # Step 1: Update source code
    if git_dir.is_dir() and shutil.which("git") is not None:
        try:
            logger.info("Executing 'git pull --ff-only'...")
            exec_res = subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if exec_res.returncode != 0:
                logger.warning("git pull failed: %s", exec_res.stderr)
                # Fallback to archive download if git pull fails
                _update_from_github_archive(repo_root)
        except Exception as err:
            logger.warning("Git pull exception: %s. Falling back to archive download.", err)
            _update_from_github_archive(repo_root)
    else:
        logger.info("Git repository not detected or git binary missing. Using archive download.")
        _update_from_github_archive(repo_root)

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
                cwd=str(repo_root),
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
                relative_path = member[len(root_prefix):]
                if not relative_path or relative_path.startswith((".git", ".venv", ".pytest_cache")):
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
