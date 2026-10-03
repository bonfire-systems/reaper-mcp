"""Tests for the REAPER-independent parts of template_tools (no REAPER needed)."""

import pytest

from reaper_mcp.template_tools import find_templates, parse_track_names, resolve_template

VOCAL = '''<TRACK {A1B2C3D4-0000-0000-0000-000000000001}
  NAME "Lead Vox"
  VOLPAN 1 0 -1 -1 1
  <FXCHAIN
    WNDRECT 0 0 0 0
    <VST "VST3: ReaEQ (Cockos)" reaeq.vst3 0 "" 1919247729{56535472656571726561657100000000} ""
      NAME "should not be picked up"
    >
  >
>
'''

DRUMS = '''<TRACK {A1B2C3D4-0000-0000-0000-000000000002}
  NAME Drums
  ISBUS 1 1
  <ITEM
    NAME "click.wav"
  >
>
<TRACK {A1B2C3D4-0000-0000-0000-000000000003}
  NAME 'Kick'
  ISBUS 0 0
>
<TRACK {A1B2C3D4-0000-0000-0000-000000000004}
  NAME ""
  ISBUS 2 -1
>
'''


@pytest.fixture
def template_dir(tmp_path):
    root = tmp_path / "TrackTemplates"
    (root / "Vocals").mkdir(parents=True)
    (root / "Drums").mkdir()
    (root / ".hidden").mkdir()
    (root / "Vocal Chain.RTrackTemplate").write_text(VOCAL)
    (root / "Vocals" / "Lead Vox.RTrackTemplate").write_text(VOCAL)
    (root / "Drums" / "Full Kit.rtracktemplate").write_text(DRUMS)
    (root / "Drums" / "Vocal Chain.RTrackTemplate").write_text(VOCAL)
    (root / "README.txt").write_text("not a template")
    (root / ".hidden" / "Secret.RTrackTemplate").write_text(VOCAL)
    return root


def test_parse_track_names_handles_quoting_and_nesting(tmp_path):
    p = tmp_path / "t.RTrackTemplate"
    p.write_text(DRUMS)
    assert parse_track_names(p) == ["Drums", "Kick", ""]
    p.write_text(VOCAL)
    assert parse_track_names(p) == ["Lead Vox"]


def test_find_templates_recurses_and_filters(template_dir):
    found = find_templates(template_dir)
    assert [t["path"] for t in found] == [
        "Drums/Full Kit",
        "Drums/Vocal Chain",
        "Vocal Chain",
        "Vocals/Lead Vox",
    ]
    kit = next(t for t in found if t["name"] == "Full Kit")
    assert kit["track_count"] == 3
    assert kit["track_names"] == ["Drums", "Kick", ""]
    assert kit["file"] == str(template_dir / "Drums" / "Full Kit.rtracktemplate")


def test_find_templates_missing_dir(tmp_path):
    assert find_templates(tmp_path / "nope") == []


def test_resolve_by_relative_path(template_dir):
    assert resolve_template("Vocals/Lead Vox", template_dir).name == "Lead Vox.RTrackTemplate"
    assert resolve_template("vocals\\lead vox.rtracktemplate", template_dir).name == (
        "Lead Vox.RTrackTemplate"
    )


def test_resolve_by_unique_name_case_insensitive(template_dir):
    assert resolve_template("lead vox", template_dir).name == "Lead Vox.RTrackTemplate"
    assert resolve_template("Full Kit", template_dir).name == "Full Kit.rtracktemplate"


def test_resolve_prefers_exact_path_over_ambiguous_name(template_dir):
    # Two files are named "Vocal Chain"; the root-level path form disambiguates.
    assert resolve_template("Vocal Chain", template_dir) == (
        template_dir / "Vocal Chain.RTrackTemplate"
    )
    assert resolve_template("Drums/Vocal Chain", template_dir) == (
        template_dir / "Drums" / "Vocal Chain.RTrackTemplate"
    )


def test_resolve_ambiguous_name_errors(template_dir):
    (template_dir / "Vocal Chain.RTrackTemplate").unlink()
    (template_dir / "Vocals" / "Vocal Chain.RTrackTemplate").write_text(VOCAL)
    with pytest.raises(ValueError, match="ambiguous"):
        resolve_template("vocal chain", template_dir)


def test_resolve_absolute_path(template_dir):
    f = template_dir / "Drums" / "Full Kit.rtracktemplate"
    assert resolve_template(str(f), template_dir) == f


def test_resolve_missing_suggests_close_match(template_dir):
    with pytest.raises(FileNotFoundError, match="Did you mean: .*Vocals/Lead Vox"):
        resolve_template("Vocals/Lead Vocal", template_dir)


def test_resolve_empty_dir(tmp_path):
    with pytest.raises(FileNotFoundError, match="No track templates"):
        resolve_template("anything", tmp_path)
