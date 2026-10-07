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


def test_parse_track_names_quote_styles_and_unquoted_names(tmp_path):
    # REAPER quotes a name with backticks when it contains both " and '; an
    # unquoted name is kept whole even when it starts and ends alike.
    p = tmp_path / "t.RTrackTemplate"
    p.write_text(
        "<TRACK\n  NAME `Say \"hi\" it's`\n>\n"
        "<TRACK\n  NAME 808\n>\n"
        "<TRACK\n  NAME \"Half'\n>\n"
    )
    assert parse_track_names(p) == ['Say "hi" it\'s', "808", "\"Half'"]


def test_parse_track_names_track_without_name_and_non_track_chunks(tmp_path):
    p = tmp_path / "t.RTrackTemplate"
    p.write_text("<NOTES\n  NAME \"not a track\"\n>\n<TRACK\n  ISBUS 0 0\n>\n")
    assert parse_track_names(p) == [""]


def test_parse_track_names_replaces_undecodable_bytes(tmp_path):
    p = tmp_path / "t.RTrackTemplate"
    p.write_bytes(b'<TRACK\n  NAME "Caf\xe9 Vox"\n>\n')
    assert parse_track_names(p) == ["Caf� Vox"]


def test_resolve_ignores_surrounding_slashes_and_extension(template_dir):
    (template_dir / "Synth X.RTrackTemplate").write_text(VOCAL)
    assert resolve_template("/Synth X/", template_dir).name == "Synth X.RTrackTemplate"
    assert resolve_template("Full Kit.RTrackTemplate", template_dir).name == (
        "Full Kit.rtracktemplate"
    )


def test_resolve_ambiguous_name_lists_every_path(template_dir):
    (template_dir / "Vocal Chain.RTrackTemplate").unlink()
    (template_dir / "Vocals" / "Vocal Chain.RTrackTemplate").write_text(VOCAL)
    with pytest.raises(ValueError) as error:
        resolve_template("vocal chain", template_dir)
    assert str(error.value) == (
        "Template name 'vocal chain' is ambiguous; use one of the full paths: "
        "Drums/Vocal Chain, Vocals/Vocal Chain"
    )


def test_resolve_missing_suggests_the_five_closest(tmp_path):
    for i in range(1, 7):
        (tmp_path / f"Pad {i}.RTrackTemplate").write_text(VOCAL)
    with pytest.raises(FileNotFoundError) as error:
        resolve_template("Pad", tmp_path)
    assert str(error.value) == (
        f"Track template 'Pad' not found in {tmp_path}. "
        "Did you mean: Pad 2, Pad 3, Pad 4, Pad 5, Pad 6? "
        "Use list_track_templates to see what is available."
    )


def test_resolve_missing_suggests_a_loose_match(tmp_path):
    (tmp_path / "Strings Section.RTrackTemplate").write_text(VOCAL)
    with pytest.raises(FileNotFoundError, match=r"Did you mean: Strings Section\? "):
        resolve_template("String", tmp_path)


def test_resolve_missing_without_a_close_match(tmp_path):
    (tmp_path / "Strings Section.RTrackTemplate").write_text(VOCAL)
    with pytest.raises(FileNotFoundError) as error:
        resolve_template("Choir", tmp_path)
    assert str(error.value) == (
        f"Track template 'Choir' not found in {tmp_path}. "
        "Use list_track_templates to see what is available."
    )
