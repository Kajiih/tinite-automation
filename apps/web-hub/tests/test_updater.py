"""Tests for Application Updater Service."""

from __future__ import annotations

import io
import zipfile
from typing import TYPE_CHECKING

from web_server import updater
from web_server.updater import (
    UpdateResult,
    check_update_available,
    get_app_version,
    perform_app_update,
    resolve_workspace_root,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_resolve_workspace_root(tmp_path: Path) -> None:
    """Verify resolve_workspace_root discovers directory containing pyproject.toml."""
    workspace = tmp_path / "my_project"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    nested_dir = workspace / "apps" / "web" / "src"
    nested_dir.mkdir(parents=True)

    assert resolve_workspace_root(nested_dir) == workspace


def test_get_app_version(tmp_path: Path) -> None:
    """Verify get_app_version extracts project version from pyproject.toml or returns None."""
    assert get_app_version(tmp_path) is None

    (tmp_path / "pyproject.toml").write_text("[project]\nversion = '0.9.5'\n")
    assert get_app_version(tmp_path) == "0.9.5"


def test_check_update_available_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify check_update_available returns dictionary with boolean update_available."""
    monkeypatch.setattr(updater, "_fetch_github_api_sha", lambda: "1234567890abcdef")
    (tmp_path / ".version_sha").write_text("1234567890abcdef\n")

    result = check_update_available(tmp_path)

    assert isinstance(result, dict)
    assert "update_available" in result
    assert isinstance(result["update_available"], bool)
    assert result["update_available"] is False
    assert result["local_sha"] == "1234567"
    assert result["remote_sha"] == "1234567"


def test_check_update_available_detects_difference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify check_update_available detects when remote and local SHAs differ."""
    monkeypatch.setattr(updater, "_fetch_github_api_sha", lambda: "abcdef1234567890")
    (tmp_path / ".version_sha").write_text("1234567890abcdef\n")

    result = check_update_available(tmp_path)

    assert result["update_available"] is True
    assert result["local_sha"] == "1234567"
    assert result["remote_sha"] == "abcdef1"


def test_check_update_available_non_git_semver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify non-git update detection compares SemVer versions without .version_sha."""
    monkeypatch.setattr(updater, "_fetch_github_api_sha", lambda: "")
    monkeypatch.setattr(updater, "_fetch_remote_pyproject_version", lambda: "0.3.0")
    (tmp_path / "pyproject.toml").write_text("[project]\nversion = '0.2.1'\n")

    result = check_update_available(tmp_path)
    assert result["update_available"] is True
    assert result["version"] == "0.2.1"

    monkeypatch.setattr(updater, "_fetch_remote_pyproject_version", lambda: "0.2.1")
    result_same = check_update_available(tmp_path)
    assert result_same["update_available"] is False


def test_perform_app_update_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify perform_app_update runs smoothly without making live network requests."""
    archive_called = False
    sync_called = False

    def fake_archive_download(_root: Path) -> None:
        nonlocal archive_called
        archive_called = True

    def fake_uv_sync(_root: Path) -> None:
        nonlocal sync_called
        sync_called = True

    monkeypatch.setattr(updater, "_update_from_github_archive", fake_archive_download)
    monkeypatch.setattr(updater, "_sync_uv_dependencies", fake_uv_sync)

    result = perform_app_update(tmp_path)

    assert isinstance(result, UpdateResult)
    assert result.success is True
    assert archive_called is True
    assert sync_called is True
    assert "successfully updated" in result.message.lower()


def test_non_git_update_flow_e2e(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end verification of non-git update detection, zip extraction, and state update."""
    # 1. Setup isolated non-git workspace with older version
    workspace = tmp_path / "installed_app"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text("[project]\nversion = '0.1.0'\n", encoding="utf-8")

    venv_dir = workspace / ".venv" / "bin"
    venv_dir.mkdir(parents=True)
    venv_file = venv_dir / "python"
    venv_file.write_text("#!/usr/bin/env python\n", encoding="utf-8")

    # 2. Mock GitHub remote responses (commit SHA and remote pyproject version)
    remote_sha = "9876543210fedcba"
    monkeypatch.setattr(updater, "_fetch_github_api_sha", lambda: remote_sha)
    monkeypatch.setattr(updater, "_fetch_remote_pyproject_version", lambda: "0.2.1")
    monkeypatch.setattr(updater, "_sync_uv_dependencies", lambda _root: None)

    # 3. Verify update detection triggers for older version
    initial_check = check_update_available(workspace)
    assert initial_check["update_available"] is True
    assert initial_check["version"] == "0.1.0"
    assert initial_check["remote_sha"] == remote_sha[:7]

    # 4. Build in-memory mock GitHub ZIP release archive
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("tinite-automation-main/pyproject.toml", "[project]\nversion = '0.2.1'\n")
        zf.writestr("tinite-automation-main/apps/web-hub/src/main.py", "print('Updated!')\n")
    mock_zip_bytes = zip_buffer.getvalue()

    monkeypatch.setattr(updater, "_download_github_archive", lambda: mock_zip_bytes)

    # 5. Execute 1-click application update
    update_result = perform_app_update(workspace)
    assert update_result.success is True

    # 6. Verify filesystem state after extraction
    updated_pyproject = (workspace / "pyproject.toml").read_text(encoding="utf-8")
    assert "version = '0.2.1'" in updated_pyproject

    version_sha_file = workspace / ".version_sha"
    assert version_sha_file.is_file()
    assert version_sha_file.read_text(encoding="utf-8").strip() == remote_sha

    # Verify .venv directory was safely preserved
    assert venv_file.is_file()

    # 7. Verify subsequent update check reports up-to-date
    subsequent_check = check_update_available(workspace)
    assert subsequent_check["update_available"] is False
    assert subsequent_check["version"] == "0.2.1"
    assert subsequent_check["local_sha"] == remote_sha[:7]
    assert subsequent_check["remote_sha"] == remote_sha[:7]
