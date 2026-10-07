"""Characterization tests for track_tools, run end to end against the fake REAPER."""

import anyio
import pytest

from tests.conftest import _call
from tests.fake_reaper.objects import ItemState

DEFAULT_INFO = {"D_VOL": 1.0, "D_PAN": 0.0, "B_MUTE": 0.0, "I_SOLO": 0.0}
OUT_OF_RANGE = {"success": False, "error": "list index out of range"}


def call_with_name(tool, **arguments):
    """`call` reserves `name` for the tool name, so tools taking `name` go through here."""
    return anyio.run(_call, tool, arguments)


def test_create_track_audio(reaper):
    reaper.add_track("first")
    result = call_with_name("create_track", name="Gtr")
    assert result == {"success": True, "track_index": 1, "name": "Gtr", "type": "audio"}
    assert [t.name for t in reaper.tracks] == ["first", "Gtr"]
    assert reaper.tracks[1].info == DEFAULT_INFO


@pytest.mark.parametrize("track_type", ["midi", "instrument"])
def test_create_track_midi_inputs(reaper, track_type):
    result = call_with_name("create_track", name="Keys", track_type=track_type)
    assert result == {"success": True, "track_index": 0, "name": "Keys", "type": track_type}
    assert reaper.tracks[0].info == {**DEFAULT_INFO, "I_RECINPUT": 4096}


def test_create_track_folder(reaper):
    result = call_with_name("create_track", name="Bus", track_type="folder")
    assert result["success"] is True
    assert reaper.tracks[0].info == {**DEFAULT_INFO, "I_FOLDERDEPTH": 1}


def test_create_track_unknown_type_is_plain(reaper):
    result = call_with_name("create_track", name="X", track_type="weird")
    assert result == {"success": True, "track_index": 0, "name": "X", "type": "weird"}
    assert reaper.tracks[0].info == DEFAULT_INFO


def test_delete_track(reaper, call):
    reaper.add_track("a")
    keep = reaper.add_track("b")
    assert call("delete_track", track_index=0) == {"success": True, "deleted_index": 0}
    assert reaper.tracks == [keep]


def test_delete_track_out_of_range(reaper, call):
    reaper.add_track("a")
    assert call("delete_track", track_index=3) == OUT_OF_RANGE
    assert len(reaper.tracks) == 1


def test_rename_track(reaper):
    state = reaper.add_track("old")
    assert call_with_name("rename_track", track_index=0, name="new") == {
        "success": True,
        "track_index": 0,
        "name": "new",
    }
    assert state.name == "new"


def test_rename_track_out_of_range(reaper):
    assert call_with_name("rename_track", track_index=0, name="x") == OUT_OF_RANGE


def test_set_track_volume_bug(reaper, call):
    state = reaper.add_track("a")
    result = call("set_track_volume", track_index=0, volume_db=-6.0)
    # BUG: reapy Track has no volume; the value lands on a throwaway proxy and the fader never moves.
    assert result == {"success": True, "track_index": 0, "volume_db": -6.0}
    assert state.info == DEFAULT_INFO


def test_set_track_volume_out_of_range(reaper, call):
    assert call("set_track_volume", track_index=0, volume_db=0.0) == OUT_OF_RANGE


def test_set_track_pan_bug(reaper, call):
    state = reaper.add_track("a")
    result = call("set_track_pan", track_index=0, pan=-0.5)
    # BUG: reapy Track has no pan; the value lands on a throwaway proxy and the pan never moves.
    assert result == {"success": True, "track_index": 0, "pan": -0.5}
    assert state.info == DEFAULT_INFO


def test_set_track_pan_out_of_range(reaper, call):
    assert call("set_track_pan", track_index=0, pan=0.0) == OUT_OF_RANGE


def test_set_track_mute_bug(reaper, call):
    state = reaper.add_track("a")
    result = call("set_track_mute", track_index=0, muted=True)
    # BUG: Track.mute is a method; assigning it shadows it on a throwaway proxy and the track stays unmuted.
    assert result == {"success": True, "track_index": 0, "muted": True}
    assert state.info["B_MUTE"] == 0.0


def test_set_track_mute_out_of_range(reaper, call):
    assert call("set_track_mute", track_index=0, muted=True) == OUT_OF_RANGE


def test_set_track_solo_bug(reaper, call):
    state = reaper.add_track("a")
    result = call("set_track_solo", track_index=0, soloed=True)
    # BUG: Track.solo is a method; assigning it shadows it on a throwaway proxy and the track stays unsoloed.
    assert result == {"success": True, "track_index": 0, "soloed": True}
    assert state.info["I_SOLO"] == 0.0


def test_set_track_solo_out_of_range(reaper, call):
    assert call("set_track_solo", track_index=0, soloed=True) == OUT_OF_RANGE


def test_get_track_info_volume_bug(reaper, call):
    reaper.add_track("a")
    result = call("get_track_info", track_index=0)
    # BUG: reapy Track has no volume, so get_track_info fails for every track.
    assert result["success"] is False
    assert "has no attribute 'volume'" in result["error"]


def test_get_track_info_item_name_bug(reaper, call):
    state = reaper.add_track("a")
    state.items.append(ItemState("(MediaItem*)0x1", 0.0, 2.0, midi=False))
    result = call("get_track_info", track_index=0)
    # BUG: reapy Item has no name, so any track with items fails before reaching volume.
    assert result["success"] is False
    assert "has no attribute 'name'" in result["error"]


def test_get_track_info_out_of_range(reaper, call):
    assert call("get_track_info", track_index=0) == OUT_OF_RANGE


def test_list_tracks_empty(reaper, call):
    assert call("list_tracks") == {"success": True, "count": 0, "tracks": []}


def test_list_tracks_volume_bug(reaper, call):
    reaper.add_track("a")
    result = call("list_tracks")
    # BUG: reapy Track has no volume, so list_tracks fails whenever the project has a track.
    assert result["success"] is False
    assert "has no attribute 'volume'" in result["error"]


def test_set_track_color(reaper, call):
    state = reaper.add_track("a")
    assert call("set_track_color", track_index=0, r=255, g=128, b=1) == {
        "success": True,
        "track_index": 0,
        "r": 255,
        "g": 128,
        "b": 1,
    }
    assert state.info["I_CUSTOMCOLOR"] == 255 | (128 << 8) | (1 << 16) | 0x1000000


def test_set_track_color_out_of_range(reaper, call):
    assert call("set_track_color", track_index=0, r=0, g=0, b=0) == OUT_OF_RANGE
