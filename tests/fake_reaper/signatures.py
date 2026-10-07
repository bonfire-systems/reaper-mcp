"""Calls into the fake are checked against the server's declared ReaScript
surface (reaper_mcp.reaper.ReaScriptAPI), the way REAPER's binding checks them.

REAPER's Python binding converts each argument with ctypes, so a call with the
wrong number of arguments, a None, or a string where a number belongs fails
there; and a project argument other than 0 (the current project) names a
project that is not open. The fake's own signatures are loose, so without
this a mutated call (a dropped argument, a None, project 1) would pass here
and fail in REAPER.
"""

import functools
import inspect
from typing import get_type_hints

from reaper_mcp.reaper import ReaScriptAPI

NUMBER_TYPES = {int: (int,), float: (int, float), bool: (bool, int)}


def _accepts(annotation, value) -> bool:
    if value is None:
        return False
    if annotation in NUMBER_TYPES:
        return isinstance(value, NUMBER_TYPES[annotation])
    if annotation is str:
        return isinstance(value, str)
    return True


def checked(name: str, function):
    """function, refusing calls REAPER's binding would refuse."""
    declared = getattr(ReaScriptAPI, name, None)
    if declared is None:
        return function
    hints = get_type_hints(declared)
    params = [p for p in inspect.signature(declared).parameters.values() if p.name != "self"]

    @functools.wraps(function)
    def call(*args):
        if len(args) != len(params):
            raise TypeError(f"{name} takes {len(params)} arguments, got {len(args)}")
        for param, value in zip(params, args, strict=True):
            if not _accepts(hints.get(param.name), value):
                raise TypeError(f"{name}: {param.name.lstrip('_')}={value!r} is not a {hints.get(param.name)}")
            if param.name == "_project" and value != 0:
                raise ValueError(f"{name}: project {value!r} is not the current project (0)")
        return function(*args)

    return call
