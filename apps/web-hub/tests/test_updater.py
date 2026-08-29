"""Tests for Application Updater Service."""

from __future__ import annotations

from typing import TYPE_CHECKING

from web_server import updater
from web_server.updater import (
    UpdateResult,
    check_update_available,
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
