from pathlib import Path
from unittest.mock import MagicMock

import pytest

from reaper_mcp import project_tools
from tests.conftest import FakeMCP


@pytest.fixture
def fake_project():
    project = MagicMock(name="Project")
    project.id = "(ReaProject*)0xDEADBEEF"
    project.name = "My Song"
    return project


@pytest.fixture
def save_project(monkeypatch, fake_project):
    """Register the tools against a FakeMCP and return the bound `save_project`."""
    monkeypatch.setattr(project_tools, "get_project", lambda: fake_project)
    fake_rpr = MagicMock(name="RPR")
    monkeypatch.setattr(project_tools, "RPR", fake_rpr)

    mcp = FakeMCP()
    project_tools.register_tools(mcp)

    tool = mcp.tools["save_project"]
    tool.rpr = fake_rpr  # expose for assertions
    return tool


def test_save_project_with_explicit_path_calls_saveprojectex(save_project, fake_project, tmp_path):
    target = tmp_path / "subdir" / "song.rpp"

    result = save_project(str(target))

    assert result == {"success": True, "project_path": str(target)}
    # The bug this regresses: `project.save(project_path)` silently maps to
    # `RPR.Main_SaveProject(proj, force_save_as)`, which does NOT accept a
    # path and raises `TypeError: 'str' object cannot be interpreted as an
    # integer` deep inside the REAPER API. Saving to an explicit path must go
    # through `Main_SaveProjectEx`, which does accept a filename.
    save_project.rpr.Main_SaveProjectEx.assert_called_once_with(
        fake_project.id, str(target), 0
    )
    fake_project.save.assert_not_called()
    assert target.parent.is_dir()


def test_save_project_creates_missing_parent_directories(save_project, tmp_path):
    target = tmp_path / "a" / "b" / "c" / "song.rpp"
    assert not target.parent.exists()

    result = save_project(str(target))

    assert result["success"] is True
    assert target.parent.is_dir()


def test_save_project_without_path_uses_default_reaper_projects_dir(
    monkeypatch, save_project, fake_project, tmp_path
):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    result = save_project("")

    expected_dir = tmp_path / "Documents" / "REAPER Projects"
    expected_path = str(expected_dir / f"{fake_project.name}.rpp")

    assert result == {"success": True, "project_path": expected_path}
    save_project.rpr.Main_SaveProjectEx.assert_called_once_with(
        fake_project.id, expected_path, 0
    )
    assert expected_dir.is_dir()


def test_save_project_reports_errors_instead_of_raising(save_project, tmp_path):
    save_project.rpr.Main_SaveProjectEx.side_effect = RuntimeError("disk full")

    result = save_project(str(tmp_path / "wherever" / "song.rpp"))

    assert result == {"success": False, "error": "disk full"}
