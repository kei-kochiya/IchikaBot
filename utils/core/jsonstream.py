"""
jsonstream.py — Incremental JSON array reader.

The Sekai master-data files are single top-level JSON arrays that can be tens of
megabytes once parsed into Python objects.  ``iter_json_array`` yields the array
elements one at a time so callers can prune, count or validate them while holding
only a single element (plus one read buffer) in memory.

It is format-agnostic: pretty-printed, minified and one-element-per-line files
all work.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

_WHITESPACE = " \t\n\r"
_NUMBER_CHARS = "0123456789.eE+-"
_CHUNK_CHARS = 1 << 20  # 1M characters per read


def _may_continue(obj: Any, buf: str, end: int) -> bool:
    """
    True if the value just decoded might be cut short by the end of the buffer.

    Objects, arrays and strings are self-delimiting, but a bare number (or a value that
    ends exactly at the buffer edge) could continue in the next chunk.
    """
    if end >= len(buf):
        return True
    return isinstance(obj, int | float) and buf[end] in _NUMBER_CHARS


def iter_json_array(path: Path | str, chunk_size: int = _CHUNK_CHARS) -> Iterator[Any]:
    """
    Yield each element of the top-level JSON array stored in *path*.

    Raises ``ValueError`` if the file is not a JSON array and
    ``json.JSONDecodeError`` (a ``ValueError``) if it is malformed.
    """
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

        if next_non_space() != "[":
            raise ValueError(f"{path}: expected a top-level JSON array")
        pos += 1

        if next_non_space() == "]":
            return

        while True:
            if next_non_space() == "":
                raise ValueError(f"{path}: unexpected end of JSON array")

            while True:
                try:
                    obj, end = decoder.raw_decode(buf, pos)
                except json.JSONDecodeError:
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
                return
            else:
                raise ValueError(f"{path}: malformed JSON array (unexpected {sep!r})")


def count_json_array(path: Path | str) -> int:
    """Count the elements of the top-level JSON array in *path* without keeping them."""
    return sum(1 for _ in iter_json_array(path))
