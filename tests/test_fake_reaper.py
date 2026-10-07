"""The fake may only expose API that reapy really has.

A fake that grows a convenient attribute reapy lacks would let a tool pass
here and fail against REAPER, which is the exact class of bug these tests
exist to catch. So every public name on a fake must exist on the reapy class
it stands for, with the same kind (method or property) and, for properties,
the same writability.
"""

import inspect
from typing import Any

import pytest
import reapy.core
from reapy import reascript_api
from reapy.core.project.time_selection import TimeSelection

from tests.fake_reaper import objects, project

PAIRS = [
    (project.FakeProject, reapy.core.Project),
    (objects.FakeTrack, reapy.core.Track),
    (objects.FakeItem, reapy.core.Item),
    (objects.FakeTake, reapy.core.Take),
    (objects.FakeFX, reapy.core.FX),
    (objects.FakeFXParam, reapy.core.FXParam),
    (objects.FakeMarker, reapy.core.Marker),
    (objects.FakeRegion, reapy.core.Region),
    (objects.FakeTimeSelection, TimeSelection),
]


def public_api(cls):
    for name, value in vars(cls).items():
        if not name.startswith("_"):
            yield name, value


@pytest.mark.parametrize(("fake", "real"), PAIRS, ids=lambda c: c.__name__)
def test_fake_exposes_only_real_api(fake, real):
    for name, value in public_api(fake):
        assert hasattr(real, name), f"{fake.__name__}.{name} does not exist on reapy.{real.__name__}"
        real_attr = inspect.getattr_static(real, name)
        if isinstance(value, property):
            assert isinstance(real_attr, property), f"{name} is not a property in reapy"
            assert bool(value.fset) == bool(real_attr.fset), (
                f"{fake.__name__}.{name} writability differs from reapy"
            )
        else:
            assert callable(real_attr) and not isinstance(real_attr, property), (
                f"{name} is a method in the fake but not in reapy"
            )


def test_fake_read_only_properties_stay_read_only():
    fake_project = project.FakeProject.__new__(project.FakeProject)
    with pytest.raises(AttributeError):
        fake_project.time_signature = (3, 4)  # pyright: ignore[reportAttributeAccessIssue]



def test_calls_are_checked_like_reapers_binding(reaper):
    # Untyped on purpose: these are calls the type checker would refuse too.
    rpr: Any = reascript_api

    with pytest.raises(TypeError, match="takes 4 arguments"):
        rpr.GetSetProjectInfo(0, "RENDER_SRATE", 1.0)
    with pytest.raises(TypeError, match="is not a"):
        rpr.GetSetProjectInfo(0, "RENDER_SRATE", None, True)
    with pytest.raises(TypeError, match="is not a"):
        rpr.CountTracks("0")
    with pytest.raises(ValueError, match="not the current project"):
        rpr.CountTracks(1)
    assert rpr.CountTracks(0) == 0


def test_unknown_info_keys_set_nothing(reaper):
    rpr: Any = reascript_api

    assert rpr.GetSetProjectInfo_String(0, "NOT_A_KEY", "x", True)[0] is False
    reaper.markers = [(1.0, "verse")]
    handle = rpr.GetRegionOrMarker(0, 0, "")
    assert rpr.GetSetRegionOrMarkerInfo_String(0, handle, "p_name", "", False)[0] is False
    rpr.GetSetRegionOrMarkerInfo_String(0, handle, "P_NAME", "chorus", True)
    assert reaper.markers == [(1.0, "chorus")]
