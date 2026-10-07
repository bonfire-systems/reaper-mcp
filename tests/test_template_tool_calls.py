"""MCP-level tests for list_track_templates and insert_track_template against the fake REAPER."""

import logging
from pathlib import Path

import pytest

TWO_TRACKS = '''<TRACK {A1B2C3D4-0000-0000-0000-000000000001}
  NAME "Bus"
  <FXCHAIN
  >
>
<TRACK {A1B2C3D4-0000-0000-0000-000000000002}
  NAME "Child"
>
'''


@pytest.fixture
def templates(reaper) -> Path:
    root = Path(reaper.GetResourcePath()) / "TrackTemplates"
    (root / "Vocals").mkdir(parents=True)
    (root / "Vocals" / "Lead Vox.RTrackTemplate").write_text(TWO_TRACKS)
    (root / "Empty.RTrackTemplate").write_text("# no tracks here\n")
    return root


def _existing(reaper):
    for name in ["A", "B", "C"]:
        reaper.add_track(name)


# list_track_templates


def test_list_track_templates_missing_folder(reaper, call):
    result = call("list_track_templates")
    assert result == {
        "success": True,
        "template_directory": str(Path(reaper.GetResourcePath()) / "TrackTemplates"),
        "count": 0,
        "templates": [],
    }


def test_list_track_templates(reaper, call, templates):
    result = call("list_track_templates")
    assert result == {
        "success": True,
        "template_directory": str(templates),
        "count": 2,
        "templates": [
            {"name": "Empty", "path": "Empty", "file": str(templates / "Empty.RTrackTemplate"),
             "track_count": 0, "track_names": []},
            {"name": "Lead Vox", "path": "Vocals/Lead Vox",
             "file": str(templates / "Vocals" / "Lead Vox.RTrackTemplate"),
             "track_count": 2, "track_names": ["Bus", "Child"]},
        ],
    }
    assert reaper.opened == []


def test_list_track_templates_unreadable_file(reaper, call, templates):
    locked = templates / "Locked.RTrackTemplate"
    locked.write_text(TWO_TRACKS)
    locked.chmod(0)
    try:
        result = call("list_track_templates")
    finally:
        locked.chmod(0o644)
    entry = next(t for t in result["templates"] if t["name"] == "Locked")
    assert result["success"] is True
    assert entry["track_count"] is None
    assert entry["track_names"] == []
    assert entry["parse_error"].startswith("[Errno 13] Permission denied")


# insert_track_template


def test_insert_track_template_appends_by_default(reaper, call, templates):
    _existing(reaper)
    result = call("insert_track_template", template="Lead Vox")
    file = templates / "Vocals" / "Lead Vox.RTrackTemplate"
    assert result == {
        "success": True,
        "template": "Lead Vox",
        "file": str(file),
        "inserted_count": 2,
        "first_track_index": 3,
        "tracks": [{"index": 3, "name": "from Lead Vox"}, {"index": 4, "name": "from Lead Vox"}],
    }
    assert reaper.opened == [str(file)]
    assert [t.name for t in reaper.tracks] == ["A", "B", "C", "from Lead Vox", "from Lead Vox"]
    assert [t.selected for t in reaper.tracks] == [False, False, False, True, True]


def test_insert_track_template_explicit_null_position_appends(reaper, call, templates):
    _existing(reaper)
    result = call("insert_track_template", template="Vocals/Lead Vox", position=None)
    assert result["first_track_index"] == 3


@pytest.mark.usefixtures("templates")
@pytest.mark.parametrize("position", [0, 1, 3])
def test_insert_track_template_at_position(reaper, call, caplog, position):
    _existing(reaper)
    with caplog.at_level(logging.WARNING, logger="reaper_mcp.template_tools"):
        result = call("insert_track_template", template="vocals/lead vox", position=position)
    assert caplog.records == []  # REAPER inserted one contiguous block: nothing to warn about
    names = ["A", "B", "C"]
    names[position:position] = ["from Lead Vox"] * 2
    assert [t.name for t in reaper.tracks] == names
    assert result["first_track_index"] == position
    assert [t["index"] for t in result["tracks"]] == [position, position + 1]
    assert [t.selected for t in reaper.tracks] == [n.startswith("from") for n in names]


def test_insert_track_template_into_empty_project(reaper, call, templates):
    result = call("insert_track_template", template="Lead Vox", position=0)
    assert result["first_track_index"] == 0
    assert [t.name for t in reaper.tracks] == ["from Lead Vox"] * 2


@pytest.mark.usefixtures("templates")
def test_insert_track_template_by_absolute_path(reaper, call):
    outside = reaper.tmp / "Elsewhere.RTrackTemplate"
    outside.write_text(TWO_TRACKS)
    result = call("insert_track_template", template=str(outside))
    assert result["template"] == "Elsewhere"
    assert result["file"] == str(outside)
    assert reaper.opened == [str(outside)]


@pytest.mark.usefixtures("templates")
@pytest.mark.parametrize("position", [-1, 4])
def test_insert_track_template_position_out_of_range(reaper, call, position):
    _existing(reaper)
    result = call("insert_track_template", template="Lead Vox", position=position)
    assert result == {
        "success": False,
        "error": f"position must be between 0 and 3 (the project has 3 tracks); got {position}",
    }
    assert reaper.opened == []
    assert [t.name for t in reaper.tracks] == ["A", "B", "C"]


def test_insert_track_template_not_found(reaper, call, templates):
    result = call("insert_track_template", template="Vocals/Lead Vocal")
    assert result == {
        "success": False,
        "error": f"Track template 'Vocals/Lead Vocal' not found in {templates}. "
                 "Did you mean: Vocals/Lead Vox? "
                 "Use list_track_templates to see what is available.",
    }
    assert reaper.opened == []


def test_insert_track_template_no_templates_installed(reaper, call):
    result = call("insert_track_template", template="Anything")
    folder = Path(reaper.GetResourcePath()) / "TrackTemplates"
    assert result == {"success": False, "error": f"No track templates found in {folder}"}


def test_insert_track_template_inserts_nothing(reaper, call, templates):
    _existing(reaper)
    result = call("insert_track_template", template="Empty", position=0)
    file = templates / "Empty.RTrackTemplate"
    assert result == {
        "success": False,
        "error": f"REAPER did not insert any tracks from {file}. "
                 "Check that the file is a valid track template.",
    }
    assert reaper.opened == [str(file)]
    assert [t.name for t in reaper.tracks] == ["A", "B", "C"]
