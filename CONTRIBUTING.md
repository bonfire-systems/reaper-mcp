# Contributing

Thanks for helping. Every pull request here is read line by line, so a small,
focused change that was tested against a real REAPER gets merged quickly; a
large or untested one usually does not. The rules below exist to make the
first kind easy.

## Before you start

- **Bug fixes**: open the pull request directly. Say how you reproduced the bug.
- **New tools, or changes to a tool's parameters**: open an issue first. Every
  tool's name, description and parameters are sent to every client on every
  session, so the tool list is kept deliberately small. Agree on the shape in
  the issue, then send the code.
- **Docs-only or agent-configuration changes** (README rewrites, `CLAUDE.md`,
  editor or agent config): please don't send these unasked. Open an issue if
  something is wrong or missing.

## Rules for a pull request

1. **One concern per pull request.** A fix for `save_project` and a new render
   option are two pull requests.
2. **Test it against a real REAPER, and say so.** State the REAPER version and
   OS you tested on, and what you ran (the tool calls and what REAPER did).
   reapy's object model does not always match what REAPER does; several bugs
   in this project's history passed every unit test and failed in REAPER.
3. **Add tests.** A fix comes with a test that fails without it. Tests run
   against the fake REAPER in `tests/fake_reaper` (see below); where you can,
   add a live test too.
4. **Disclose AI assistance** in the pull request description, if you used it.
   AI-written code is welcome on the same terms as any other: you have run it,
   and you can explain every line of it if asked.

## Development setup

```bash
git clone https://github.com/bonfire-systems/reaper-mcp.git
cd reaper-mcp
uv sync --extra dev        # or: pip install -e ".[dev]"
uv run pytest              # fake-REAPER tests; no REAPER needed
uv run ruff check src tests
```

## How the code is organised

- Tools are module-level functions in `src/reaper_mcp/*_tools.py`, listed in
  each module's `TOOLS` tuple and registered by `server.py`, which serialises
  them behind one lock and turns an exception into
  `{"success": False, "error": ...}`. Tool parameters are keyword-only
  (`def tool(*, track_index: int, ...)`): they are the tool's JSON schema.
- `src/reaper_mcp/reaper.py` is the only module that imports reapy. ReaScript
  functions are called through its typed `RPR`; add a function to its
  `ReaScriptAPI` protocol when you use a new one.
- When reapy and REAPER disagree, REAPER wins. Known cases, each pinned by a
  test in `tests/contract`: reapy's `Track` has no `volume`/`pan`; `solo()`
  does nothing on REAPER 7.82 (use `I_SOLO`); `Project.time_signature` is
  `(bpm, numerator)`; a missing envelope is a truthy null-pointer string (use
  `reaper.is_null`); render settings take a directory in `RENDER_FILE` and a
  name in `RENDER_PATTERN`.

## Tests

- **Unit tests** call each tool through the real MCP client against the fake
  REAPER in `tests/fake_reaper`. The fake may only expose API that reapy
  really has (`tests/test_fake_reaper.py` enforces this), and calls into it
  are checked against `ReaScriptAPI` the way REAPER's binding checks them.
  Do not add fake-only API to make a test pass; if the fake is missing
  something REAPER does, add it faithfully and say so in the pull request.
- **The tool schema snapshot** (`tests/snapshots/tool_schemas.json`) pins every
  tool's name, description and parameters. If you change them on purpose,
  regenerate it and include the diff:
  `UPDATE_TOOL_SCHEMAS=1 uv run pytest tests/test_tool_schemas.py`
- **Live tests** (`tests/live`, `tests/contract`) drive a running REAPER:
  `uv run pytest --live`. They fail rather than skip when REAPER is not
  reachable. They work in the current project, emptying it before and after
  each test, so run them on a scratch project. If REAPER opens a dialog, the
  run stops and names it instead of hanging.

## Live tests: connecting reapy to REAPER

With REAPER **closed** (it rewrites `reaper.ini` when it quits), run once:

```bash
uv run python -c "import reapy; reapy.configure_reaper()"
```

then start REAPER. This enables Python for ReaScript, adds a web interface on
port 2307 and registers reapy's server action. The action points into the
environment you ran it from, so run it again if you recreate that
environment. (`scripts/enable_reapy.py`, run from inside REAPER, does the same
from the other side.)

## Style

Match the surrounding code. `ruff check src tests` must pass. Keep functions
short and nesting shallow; the maintainers run stricter checks (complexity
and size ceilings, type checking, mutation testing) before merging, and will
point out anything they flag.

## Commit messages

Say what changed and why in plain words. Reference the issue if there is one.
