import functools
import logging
import threading

from mcp.server import MCPServer

logger = logging.getLogger("reaper_mcp.server")

_server = MCPServer("reaper-mcp")

# reapy drives REAPER over a single shared socket: reapy.tools.network.Client
# keeps one module-global connection and its request() does an unguarded
# send-then-recv round trip. Two concurrent calls interleave their length
# prefixes and payloads on that socket and can read each other's replies.
#
# Under the old mcp.server.fastmcp this was unreachable, because v1 invoked
# sync tool functions inline on the event loop. MCP v2 dispatches them through
# anyio.to_thread.run_sync instead, so any client issuing parallel tool calls
# would run two of our tools on different worker threads at once. Every tool
# here is a sync def that ends up in reapy, so serialize them all behind one
# lock. This matches the effective v1 behaviour (one REAPER call at a time)
# without blocking the event loop.
_reaper_lock = threading.Lock()


class _SerializedTools:
    """Proxies MCPServer, wrapping each registered tool in the REAPER lock."""

    def __init__(self, server: MCPServer) -> None:
        self._server = server

    def tool(self, *args, **kwargs):
        register = self._server.tool(*args, **kwargs)

        def decorator(fn):
            @functools.wraps(fn)
            def locked(*fn_args, **fn_kwargs):
                with _reaper_lock:
                    return fn(*fn_args, **fn_kwargs)

            return register(locked)

        return decorator

    def __getattr__(self, name):
        return getattr(self._server, name)


mcp = _server
_registrar = _SerializedTools(_server)

# Import each tool module's register_tools function and call it with the mcp instance.
# The imports must happen after mcp is created to avoid circular dependencies.
from reaper_mcp.project_tools import register_tools as _reg_project
from reaper_mcp.track_tools import register_tools as _reg_track
from reaper_mcp.midi_tools import register_tools as _reg_midi
from reaper_mcp.fx_tools import register_tools as _reg_fx
from reaper_mcp.audio_tools import register_tools as _reg_audio
from reaper_mcp.mixing_tools import register_tools as _reg_mixing
from reaper_mcp.render_tools import register_tools as _reg_render
from reaper_mcp.mastering_tools import register_tools as _reg_mastering
from reaper_mcp.analysis_tools import register_tools as _reg_analysis

_reg_project(_registrar)
_reg_track(_registrar)
_reg_midi(_registrar)
_reg_fx(_registrar)
_reg_audio(_registrar)
_reg_mixing(_registrar)
_reg_render(_registrar)
_reg_mastering(_registrar)
_reg_analysis(_registrar)
