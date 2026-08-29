"""
Tests for Application Updater Service
"""

from __future__ import annotations

from pathlib import Path
import pytest

from web_server.updater import UpdateResult, perform_app_update


class TestAppUpdater:
    """Tests for the cross-platform updater service."""

    def test_perform_app_update_execution(self, tmp_path: Path):
        """Verify perform_app_update runs smoothly and returns valid UpdateResult."""
        result = perform_app_update(tmp_path)

        assert isinstance(result, UpdateResult)
        assert result.success is True
        assert "successfully updated" in result.message.lower()
