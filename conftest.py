"""Make the repository root importable as `project_titan_x`.

WHY THIS EXISTS. 99 test modules import `from project_titan_x.engines...`.
That resolves in the private working copy purely because that checkout's
directory is literally named `project_titan_x` and its parent happens to be on
`sys.path`. The public repository checks out as `titan-x`, so the name does not
resolve and every one of those modules fails at collection with
`ModuleNotFoundError: No module named 'project_titan_x'`.

The fix is not to rewrite 99 files. The repository root genuinely *is* the
`project_titan_x` package -- it even has the `__init__.py` -- and the only thing
missing is a binding from the name to this root that does not depend on what the
containing directory happens to be called.

WHY THE ROOT `__init__.py` IS EXECUTED rather than faked. A first attempt bound
a bare `types.ModuleType` with `__path__` set, which made the submodule imports
work. It was wrong: a bare module never runs `__init__.py`, and this project's
`__init__.py` sets `pandas.set_option("future.no_silent_downcasting", True)`.
Skipping it leaves object-dtype `.fillna` silently downcasting across the whole
codebase, so the tests would have run green against different pandas behaviour
than the application gets -- a failure that passes. Loading through a real spec
executes the file exactly as a normal import would, and also supplies the
`__version__` three test modules import.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
_PKG = "project_titan_x"

# `pythonpath = ["."]` in pyproject.toml covers pytest, but scripts and doctests
# invoked directly do not read that setting.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _already_importable() -> bool:
    """True if a real `project_titan_x` package is already on the path.

    Checked rather than assumed: in the private working copy the package IS
    importable for real, and shadowing it there would silently change which
    files the tests exercise.
    """
    if _PKG in sys.modules:
        return True
    try:
        return importlib.util.find_spec(_PKG) is not None
    except (ImportError, ValueError):
        # A partially-initialised or namespace-shadowed parent can raise here.
        return False


def _bind_root_as_package() -> None:
    """Import this repository root under the name `project_titan_x`."""
    init = ROOT / "__init__.py"
    if not init.is_file():
        # Nothing to bind to. Left deliberately silent rather than raising: a
        # checkout without the root __init__.py is a packaging problem, and the
        # resulting ImportError names the real missing module far more usefully
        # than an exception thrown from conftest collection would.
        return

    spec = importlib.util.spec_from_file_location(
        _PKG, init, submodule_search_locations=[str(ROOT)]
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        return

    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec_module so that any self-referential import inside
    # __init__.py resolves to this partially-initialised module instead of
    # recursing, which is what the import system itself does.
    sys.modules[_PKG] = module
    try:
        spec.loader.exec_module(module)
    except Exception:  # pragma: no cover - never leave a broken entry behind
        del sys.modules[_PKG]
        raise


if not _already_importable():
    _bind_root_as_package()
