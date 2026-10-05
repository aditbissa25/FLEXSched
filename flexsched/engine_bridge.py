"""Bridge between Python and the compiled C++ engine.

Integration style: subprocess + JSON over stdin/stdout.
    Python  --(JSON request on stdin)-->  flexsched_engine(.exe)
    Python  <--(JSON response on stdout)--

Alternatives considered (good to mention in interviews):
    * pybind11 extension module - fastest, but couples the build to one exact
      Python version/compiler and complicates packaging on Windows.
    * ctypes + C ABI shared library - no compile-time coupling, but manual
      memory management across the boundary and no type safety.
    * subprocess + JSON (chosen) - ~ms of overhead per call, irrelevant for
      a planner that runs a few times a day; in exchange the engine is a
      standalone tool that can be tested, debugged and replaced on its own.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from . import config


class EngineError(RuntimeError):
    """The engine crashed or returned something unusable."""


class EngineInputError(EngineError):
    """The engine rejected our request (exit code 2)."""


class EngineNotFoundError(EngineError):
    pass


_EXE = "flexsched_engine.exe" if os.name == "nt" else "flexsched_engine"


def find_engine() -> Path:
    """Locate the engine binary: env var, then common build folders, then PATH."""
    override = os.environ.get("FLEXSCHED_ENGINE")
    candidates: list[Optional[Path]] = [Path(override)] if override else []
    build = config.PROJECT_ROOT / "build"
    candidates += [build / _EXE, build / "Release" / _EXE, build / "Debug" / _EXE]
    on_path = shutil.which("flexsched_engine")
    candidates.append(Path(on_path) if on_path else None)

    for path in candidates:
        if path is not None and path.is_file():
            return path
    raise EngineNotFoundError(
        "C++ engine not found. Build it first:\n"
        "    cmake -S engine -B build -G Ninja -DCMAKE_BUILD_TYPE=Release\n"
        "    cmake --build build\n"
        "or set FLEXSCHED_ENGINE to the path of flexsched_engine.")


def run_engine(request: dict, timeout: float = 30.0,
               engine_path: Optional[Path] = None) -> dict:
    """Send one request to the engine and return the parsed response."""
    exe = engine_path or find_engine()
    try:
        proc = subprocess.run(
            [str(exe)],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,  # we inspect the return code ourselves
        )
    except subprocess.TimeoutExpired as exc:
        raise EngineError(f"engine timed out after {timeout}s") from exc

    if proc.returncode == 2:
        raise EngineInputError(proc.stderr.strip())
    if proc.returncode != 0:
        raise EngineError(f"engine failed (exit {proc.returncode}): {proc.stderr.strip()}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise EngineError(f"engine returned invalid JSON: {proc.stdout[:200]!r}") from exc
