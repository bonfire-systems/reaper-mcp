"""The fake may only expose API that reapy really has.

A fake that grows a convenient attribute reapy lacks would let a tool pass
here and fail against REAPER, which is the exact class of bug these tests
exist to catch. So every public name on a fake must exist on the reapy class
it stands for, with the same kind (method or property) and, for properties,
the same writability.
"""

import inspect

import pytest
import reapy.core
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

