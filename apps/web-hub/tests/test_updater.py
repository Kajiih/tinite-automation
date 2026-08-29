"""Tests for Application Updater Service."""

from __future__ import annotations

from typing import TYPE_CHECKING

from web_server.updater import (
    UpdateResult,
    check_update_available,
    perform_app_update,
    resolve_workspace_root,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestAppUpdater:
    """Tests for the cross-platform updater service."""

    def test_resolve_workspace_root(self, tmp_path: Path) -> None:
        """Verify resolve_workspace_root discovers directory containing pyproject.toml."""
        workspace = tmp_path / "my_project"
        workspace.mkdir()
        (workspace / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        nested_dir = workspace / "apps" / "web" / "src"
        nested_dir.mkdir(parents=True)

        assert resolve_workspace_root(nested_dir) == workspace

    def test_check_update_available_contract(self, tmp_path: Path) -> None:
        """Verify check_update_available returns dictionary with boolean update_available."""
        result = check_update_available(tmp_path)

        assert isinstance(result, dict)
        assert "update_available" in result
        assert isinstance(result["update_available"], bool)

    def test_perform_app_update_execution(self, tmp_path: Path) -> None:
        """Verify perform_app_update runs smoothly and returns valid UpdateResult."""
        result = perform_app_update(tmp_path)

        assert isinstance(result, UpdateResult)
        assert result.success is True
        assert "successfully updated" in result.message.lower()
