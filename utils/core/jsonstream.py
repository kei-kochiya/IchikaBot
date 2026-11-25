"""Incremental JSON array reader (`iter_json_array`) for multi-MB Sekai master-data files."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

_WHITESPACE = " \t\n\r"
_NUMBER_CHARS = "0123456789.eE+-"
_CHUNK_CHARS = 1 << 16  # 64K chars: small buffer fits L2 cache and cuts peak memory


def _may_continue(obj: Any, buf: str, end: int) -> bool:
    """Return True if a decoded bare number could continue across the read-buffer boundary."""
    if isinstance(obj, bool) or not isinstance(obj, int | float):
        return False
    if end >= len(buf):
        return True
    return all(c in _NUMBER_CHARS for c in buf[end:])


def _is_chunk_boundary_error(err: json.JSONDecodeError, buf: str) -> bool:
    """True only when *err* can plausibly be resolved by reading more bytes."""
    if err.msg.startswith("Unterminated string"):
        return True
    return err.pos >= len(buf) - 6


def iter_json_array(path: Path | str, chunk_size: int = _CHUNK_CHARS) -> Iterator[Any]:
    """Yield each element of a top-level JSON array in *path*; raises `ValueError` if invalid."""
    decoder = json.JSONDecoder()
    with open(path, encoding="utf-8") as f:
        buf = ""
        pos = 0

        def next_non_space() -> str:
            """Advance *pos* to the next non-whitespace char and return it ('' at EOF)."""
            nonlocal buf, pos
            while True:
                end = len(buf)
                while pos < end and buf[pos] in _WHITESPACE:
                    pos += 1
                if pos < end:
                    return buf[pos]
                chunk = f.read(chunk_size)
                if not chunk:
                    return ""
                buf, pos = chunk, 0

        def ensure_eof() -> None:
            nonlocal pos
            pos += 1
            trailing = next_non_space()
            if trailing:
                raise ValueError(f"{path}: trailing data after JSON array ({trailing!r})")

        if next_non_space() != "[":
            raise ValueError(f"{path}: expected a top-level JSON array")
        pos += 1

        if next_non_space() == "]":
            ensure_eof()
            return

        while True:
            if next_non_space() == "":
                raise ValueError(f"{path}: unexpected end of JSON array")

            while True:
                try:
                    obj, end = decoder.raw_decode(buf, pos)
                except json.JSONDecodeError as err:
                    if not _is_chunk_boundary_error(err, buf):
                        raise
                    chunk = f.read(chunk_size)
                    if not chunk:
                        raise
                    buf, pos = buf[pos:] + chunk, 0
                    continue
                if _may_continue(obj, buf, end):
                    chunk = f.read(chunk_size)
                    if chunk:
                        buf, pos = buf[pos:] + chunk, 0
                        continue
                break

            yield obj
            pos = end

            sep = next_non_space()
            if sep == ",":
                pos += 1
            elif sep == "]":
                ensure_eof()
                return
            else:
                raise ValueError(f"{path}: malformed JSON array (unexpected {sep!r})")


def count_json_array(path: Path | str) -> int:
    """Count the elements of the top-level JSON array in *path* without keeping them."""
    return sum(1 for _ in iter_json_array(path))
