"""Converter registry for any2any.

Uses a reader/writer architecture: each format registers a reader
(file → ImageData) and/or a writer (ImageData → file).  Any format
with a reader can be converted to any format with a writer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PIL import Image


@dataclass
class ImageData:
    """Intermediate representation carrying frames and metadata."""

    frames: list[Image.Image]
    metadata: dict[str, object] = field(default_factory=dict)


# Type aliases.
ReaderFunc = Callable[[Path], ImageData]
WriterFunc = Callable[[ImageData, Path], None]

# Extension → reader / writer.
_readers: dict[str, ReaderFunc] = {}
_writers: dict[str, WriterFunc] = {}


def register_reader(*exts: str):
    """Register a reader function for one or more extensions."""

    def decorator(func: ReaderFunc) -> ReaderFunc:
        for ext in exts:
            _readers[ext.lower()] = func
        return func

    return decorator


def register_writer(*exts: str):
    """Register a writer function for one or more extensions."""

    def decorator(func: WriterFunc) -> WriterFunc:
        for ext in exts:
            _writers[ext.lower()] = func
        return func

    return decorator


def can_convert(in_ext: str, out_ext: str) -> bool:
    """Check whether a conversion path exists."""
    return in_ext.lower() in _readers and out_ext.lower() in _writers


def read_image(path: Path) -> ImageData:
    """Read an image file into the intermediate representation."""
    ext = path.suffix.lower().lstrip(".")
    reader = _readers.get(ext)
    if reader is None:
        raise ValueError(f"no reader available for .{ext}")
    return reader(path)


def write_image(data: ImageData, path: Path) -> None:
    """Write an ImageData to a file."""
    ext = path.suffix.lower().lstrip(".")
    writer = _writers.get(ext)
    if writer is None:
        raise ValueError(f"no writer available for .{ext}")
    path.parent.mkdir(parents=True, exist_ok=True)
    writer(data, path)


def readable_extensions() -> set[str]:
    return set(_readers.keys())


def writable_extensions() -> set[str]:
    return set(_writers.keys())


# Import converter modules to trigger registration.
from any2any.converters import image as _image  # noqa: E402, F401
