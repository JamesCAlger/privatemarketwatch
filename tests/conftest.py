"""Pytest safeguards for production output artifacts."""

from __future__ import annotations

import builtins
import io
import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROTECTED_OUTPUT_ROOTS = (
    (PROJECT_ROOT / "data" / "output").resolve(strict=False),
    (PROJECT_ROOT / "frontend" / "public" / "data").resolve(strict=False),
)
_WRITE_MODE_CHARS = frozenset("wax+")

_ORIGINAL_BUILTINS_OPEN = builtins.open
_ORIGINAL_IO_OPEN = io.open


def _is_protected_path(path: Path) -> bool:
    resolved = path.resolve(strict=False)
    return any(resolved == root or resolved.is_relative_to(root) for root in PROTECTED_OUTPUT_ROOTS)


def _should_block_open(file: Any, mode: str) -> tuple[bool, Path | None]:
    if not isinstance(file, (str, bytes, os.PathLike)):
        return False, None
    if not any(char in mode for char in _WRITE_MODE_CHARS):
        return False, None

    path = Path(file)
    if _is_protected_path(path):
        return True, path.resolve(strict=False)
    return False, None


def _guarded_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
    block, protected_path = _should_block_open(file, mode)
    if block:
        raise AssertionError(f"pytest attempted to write protected output path: {protected_path} (mode={mode!r})")
    return _ORIGINAL_BUILTINS_OPEN(file, mode, *args, **kwargs)


def _guarded_io_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
    block, protected_path = _should_block_open(file, mode)
    if block:
        raise AssertionError(f"pytest attempted to write protected output path: {protected_path} (mode={mode!r})")
    return _ORIGINAL_IO_OPEN(file, mode, *args, **kwargs)


builtins.open = _guarded_open
io.open = _guarded_io_open
