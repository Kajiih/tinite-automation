"""Tests for Application Updater Service."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import threading
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from typing import TYPE_CHECKING

from web_server import updater
from web_server.server import WebHubRequestHandler
from web_server.updater import (
    TINITE_AUTOMATION_ENABLE_GIT_UPDATE_ENV,
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
    """Verify check_update_available returns dictionary with boolean in git mode by default."""
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
    """Verify check_update_available detects remote/local SHA difference in git mode."""
    monkeypatch.setattr(updater, "_fetch_github_api_sha", lambda: "abcdef1234567890")
    (tmp_path / ".version_sha").write_text("1234567890abcdef\n")

    result = check_update_available(tmp_path)

    assert result["update_available"] is True
    assert result["local_sha"] == "1234567"
    assert result["remote_sha"] == "abcdef1"


def test_check_update_available_disabled_via_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify git update can be explicitly disabled via environment variable."""
    monkeypatch.setenv(TINITE_AUTOMATION_ENABLE_GIT_UPDATE_ENV, "0")
    monkeypatch.setattr(updater, "_fetch_remote_pyproject_version", lambda: "0.2.1")
    (tmp_path / "pyproject.toml").write_text("[project]\nversion = '0.1.0'\n")
    (tmp_path / ".version_sha").write_text("1234567890abcdef\n")

    result = check_update_available(tmp_path)
    assert result["update_available"] is True
    assert not result["local_sha"]
    assert not result["remote_sha"]


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


def test_is_git_update_enabled_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify _is_git_update_enabled parses booleans, defaults, and env strings robustly."""
    # Explicit arguments override env
    assert updater._is_git_update_enabled(enable_git=True) is True  # ruff: ignore[private-member-access]
    assert updater._is_git_update_enabled(enable_git=False) is False  # ruff: ignore[private-member-access]

    # Default when env is unset
    monkeypatch.delenv(TINITE_AUTOMATION_ENABLE_GIT_UPDATE_ENV, raising=False)
    assert updater._is_git_update_enabled() is True  # ruff: ignore[private-member-access]

    # Truthy env values (with whitespace)
    for val in ("1", "true", "yes", "on", " TRUE ", " 1 "):
        monkeypatch.setenv(TINITE_AUTOMATION_ENABLE_GIT_UPDATE_ENV, val)
        assert updater._is_git_update_enabled() is True  # ruff: ignore[private-member-access]

    # Falsy env values (with whitespace)
    for val in ("0", "false", "no", "off", " 0 ", " FALSE "):
        monkeypatch.setenv(TINITE_AUTOMATION_ENABLE_GIT_UPDATE_ENV, val)
        assert updater._is_git_update_enabled() is False  # ruff: ignore[private-member-access]


def test_extract_zip_contents_traversal_defense(tmp_path: Path) -> None:
    """Verify _extract_zip_contents ignores entries attempting directory traversal outside root."""
    target_dir = tmp_path / "app_root"
    target_dir.mkdir()
    outside_file = tmp_path / "escaped.txt"

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("root-dir/safe.txt", "safe content")
        zf.writestr("root-dir/../escaped.txt", "malicious content")

    updater._extract_zip_contents(zip_buffer.getvalue(), target_dir)  # ruff: ignore[private-member-access]

    assert (target_dir / "safe.txt").read_text() == "safe content"
    assert not outside_file.exists()


def test_perform_app_update_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify perform_app_update runs smoothly without making live network requests."""
    archive_called = False
    sync_called = False

    def fake_archive_download(_root: Path) -> bool:
        nonlocal archive_called
        archive_called = True
        return True

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


def test_perform_app_update_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify perform_app_update reports failure and skips uv sync when download fails."""
    sync_called = False

    def fake_archive_fail(_root: Path) -> bool:
        return False

    def fake_uv_sync(_root: Path) -> None:
        nonlocal sync_called
        sync_called = True

    monkeypatch.setattr(updater, "_update_from_github_archive", fake_archive_fail)
    monkeypatch.setattr(updater, "_sync_uv_dependencies", fake_uv_sync)

    result = perform_app_update(tmp_path)

    assert isinstance(result, UpdateResult)
    assert result.success is False
    assert sync_called is False
    assert "failed" in result.message.lower()


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


def test_web_server_http_update_lifecycle_e2e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end HTTP integration test for /api/check-update and /api/update endpoints."""
    # 1. Setup isolated workspace with older version
    workspace = tmp_path / "app_workspace"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text("[project]\nversion = '0.1.0'\n", encoding="utf-8")

    # 2. Mock updater methods to operate on this workspace
    monkeypatch.setattr(updater, "resolve_workspace_root", lambda _start=None: workspace)
    monkeypatch.setattr(updater, "_fetch_remote_pyproject_version", lambda: "0.2.1")
    monkeypatch.setattr(updater, "_fetch_github_api_sha", lambda: "")
    monkeypatch.setattr(updater, "_sync_uv_dependencies", lambda _root: None)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("tinite-automation-main/pyproject.toml", "[project]\nversion = '0.2.1'\n")
    mock_zip_bytes = zip_buffer.getvalue()
    monkeypatch.setattr(updater, "_download_github_archive", lambda: mock_zip_bytes)

    # 3. Start real HTTP server on ephemeral port (port 0)
    server = ThreadingHTTPServer(("127.0.0.1", 0), WebHubRequestHandler)
    port = server.server_address[1]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    base_url = f"http://127.0.0.1:{port}"

    try:
        # 4. HTTP GET /api/check-update -> verify update is available
        check_url = f"{base_url}/api/check-update"
        with urllib.request.urlopen(check_url, timeout=5) as resp:  # ruff: ignore[suspicious-url-open-usage]
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["update_available"] is True
            assert data["version"] == "0.1.0"

        # 5. HTTP POST /api/update -> trigger in-place application update
        update_url = f"{base_url}/api/update"
        post_req = urllib.request.Request(  # ruff: ignore[suspicious-url-open-usage]
            update_url,
            method="POST",
        )
        with urllib.request.urlopen(post_req, timeout=5) as resp:  # ruff: ignore[suspicious-url-open-usage]
            assert resp.status == 200
            post_data = json.loads(resp.read().decode("utf-8"))
            assert post_data["success"] is True

        # 6. HTTP GET /api/check-update -> verify updated state
        with urllib.request.urlopen(check_url, timeout=5) as resp:  # ruff: ignore[suspicious-url-open-usage]
            assert resp.status == 200
            data_after = json.loads(resp.read().decode("utf-8"))
            assert data_after["update_available"] is False
            assert data_after["version"] == "0.2.1"
    finally:
        server.shutdown()
        server.server_close()


def _setup_git_test_environment(tmp_path: Path) -> tuple[Path, Path]:
    """Create a bare remote and a local git clone where remote is ahead by one commit."""
    git_bin = shutil.which("git")
    assert git_bin is not None

    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test Committer",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test Committer",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    remote_repo = tmp_path / "remote.git"
    subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [git_bin, "init", "--bare", "-b", "main", str(remote_repo)],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    local_repo = tmp_path / "local_repo"
    local_repo.mkdir()
    subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [git_bin, "init", "-b", "main"],
        cwd=str(local_repo),
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [git_bin, "remote", "add", "origin", str(remote_repo)],
        cwd=str(local_repo),
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    (local_repo / "pyproject.toml").write_text("[project]\nversion = '0.1.0'\n", encoding="utf-8")
    subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [git_bin, "add", "."],
        cwd=str(local_repo),
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [git_bin, "commit", "-m", "initial commit"],
        cwd=str(local_repo),
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [git_bin, "push", "-u", "origin", "main"],
        cwd=str(local_repo),
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    dev_clone = tmp_path / "dev_clone"
    subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [git_bin, "clone", str(remote_repo), str(dev_clone)],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    (dev_clone / "pyproject.toml").write_text("[project]\nversion = '0.2.1'\n", encoding="utf-8")
    subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [git_bin, "add", "."],
        cwd=str(dev_clone),
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [git_bin, "commit", "-m", "release v0.2.1"],
        cwd=str(dev_clone),
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [git_bin, "push", "origin", "main"],
        cwd=str(dev_clone),
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    return local_repo, remote_repo


def test_git_update_flow_e2e(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end verification of Git-based update detection and git pull execution by default."""
    local_repo, _remote_repo = _setup_git_test_environment(tmp_path)
    monkeypatch.setattr(updater, "_sync_uv_dependencies", lambda _root: None)

    # 1. Verify update detection triggers in git mode by default
    initial_check = check_update_available(local_repo)
    assert initial_check["update_available"] is True
    assert initial_check["version"] == "0.1.0"
    assert bool(initial_check["local_sha"])
    assert bool(initial_check["remote_sha"])
    assert initial_check["local_sha"] != initial_check["remote_sha"]

    # 2. Execute git update (git pull origin main --ff-only) by default
    update_result = perform_app_update(local_repo)
    assert update_result.success is True

    # 3. Verify repository file is fast-forwarded to version 0.2.1
    updated_pyproject = (local_repo / "pyproject.toml").read_text(encoding="utf-8")
    assert "version = '0.2.1'" in updated_pyproject

    # 4. Verify subsequent check confirms repository is up-to-date
    subsequent_check = check_update_available(local_repo)
    assert subsequent_check["update_available"] is False
    assert subsequent_check["version"] == "0.2.1"
    assert subsequent_check["local_sha"] == subsequent_check["remote_sha"]


def test_web_server_git_http_update_lifecycle_e2e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end HTTP integration test for Git-enabled update flow."""
    local_repo, _remote_repo = _setup_git_test_environment(tmp_path)
    monkeypatch.setenv(TINITE_AUTOMATION_ENABLE_GIT_UPDATE_ENV, "1")
    monkeypatch.setattr(updater, "resolve_workspace_root", lambda _start=None: local_repo)
    monkeypatch.setattr(updater, "_sync_uv_dependencies", lambda _root: None)

    server = ThreadingHTTPServer(("127.0.0.1", 0), WebHubRequestHandler)
    port = server.server_address[1]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    base_url = f"http://127.0.0.1:{port}"

    try:
        check_url = f"{base_url}/api/check-update"
        with urllib.request.urlopen(check_url, timeout=5) as resp:  # ruff: ignore[suspicious-url-open-usage]
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["update_available"] is True
            assert data["version"] == "0.1.0"
            assert bool(data["local_sha"])
            assert bool(data["remote_sha"])
            assert data["local_sha"] != data["remote_sha"]

        update_url = f"{base_url}/api/update"
        post_req = urllib.request.Request(  # ruff: ignore[suspicious-url-open-usage]
            update_url,
            method="POST",
        )
        with urllib.request.urlopen(post_req, timeout=5) as resp:  # ruff: ignore[suspicious-url-open-usage]
            assert resp.status == 200
            post_data = json.loads(resp.read().decode("utf-8"))
            assert post_data["success"] is True

        with urllib.request.urlopen(check_url, timeout=5) as resp:  # ruff: ignore[suspicious-url-open-usage]
            assert resp.status == 200
            data_after = json.loads(resp.read().decode("utf-8"))
            assert data_after["update_available"] is False
            assert data_after["version"] == "0.2.1"
            assert data_after["local_sha"] == data_after["remote_sha"]
    finally:
        server.shutdown()
        server.server_close()
