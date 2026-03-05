import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from bin.screenshot_sync.screenshot_sync import SyncConfig, PLIST_LABEL, PLIST_PATH

@pytest.fixture
def mock_config_file(tmp_path):
    config_dir = tmp_path / ".config/screenshot-sync"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "config.json"
    data = {
        "vm_host": "test-vm",
        "remote_dir": "/remote/path/"
    }
    config_file.write_text(json.dumps(data))
    return config_file

def test_config_loading(mock_config_file, monkeypatch):
    monkeypatch.setattr("bin.screenshot_sync.screenshot_sync.CONFIG_FILE",
 mock_config_file)
    config = SyncConfig.load()
    assert config.vm_host == "test-vm"
    assert config.remote_dir == "/remote/path/"
    assert config.screenshot_dir == Path.home() / "Desktop"

def test_config_env_override(mock_config_file, monkeypatch):
    monkeypatch.setattr("bin.screenshot_sync.screenshot_sync.CONFIG_FILE",
 mock_config_file)
    monkeypatch.setenv("SCREENSHOT_DIR", "/custom/screenshots")
    config = SyncConfig.load()
    assert config.screenshot_dir == Path("/custom/screenshots")

@patch("subprocess.run")
def test_sync_command_construction(mock_run, mock_config_file, monkeypatch):
    monkeypatch.setattr("bin.screenshot_sync.screenshot_sync.CONFIG_FILE",
 mock_config_file)
    from bin.screenshot_sync.screenshot_sync import run_sync
    
    run_sync()
    
    # Check if rsync was called with correct arguments
    args, kwargs = mock_run.call_args
    cmd = args[0]
    assert cmd[0] == "rsync"
    assert "test-vm:/remote/path/" in cmd
    assert "--include=Screenshot *.png" in cmd
    assert "--include=Screen Shot *.png" in cmd
    assert "--exclude=*" in cmd

def test_uv_tool_install_and_path_verification():
    # This test actually performs the installation from the root directory
    root_path = Path(__file__).parent.parent
    expected_tool_path = Path.home() / ".local/bin/screenshot-sync"

    # Force reinstall with required dependency
    subprocess.run(["uv", "tool", "install", str(root_path), "--with", "python-dotenv", "--force"], check=True)

    
    # Assert path existence
    assert expected_tool_path.exists(), f"Tool not found at {expected_tool_path}"
    
    # Assert execution
    result = subprocess.run([str(expected_tool_path), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "Sync screenshots to a remote VM" in result.stdout

@patch("subprocess.run")
def test_plist_generation(mock_run, mock_config_file, monkeypatch, tmp_path):
    monkeypatch.setattr("bin.screenshot_sync.screenshot_sync.CONFIG_FILE",
 mock_config_file)
    
    # Mock PLIST_PATH to a temp location
    temp_plist = tmp_path / "test.plist"
    monkeypatch.setattr("bin.screenshot_sync.screenshot_sync.PLIST_PATH", temp_plist)
    
    # Mock tool path existence
    with patch("pathlib.Path.exists", return_value=True):
        from bin.screenshot_sync.screenshot_sync import install_launchd
        install_launchd()
    
    assert temp_plist.exists()
    content = temp_plist.read_text()
    assert "<string>test-vm</string>" not in content # it uses tool sync, not raw values
    assert f"<string>{PLIST_LABEL}</string>" in content
    assert "WatchPaths" in content
    assert str(Path.home() / "Desktop") in content
