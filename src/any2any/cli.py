"""Command-line interface for any2any."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from any2any import __version__
from any2any.converters import ImageData, can_convert, read_image, write_image


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="any2any",
        description="Convert files from one format to another.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Path to the input file.",
    )
    parser.add_argument(
        "output",
        help=(
            "Path to the output file, or a pattern like '*.jpg' to "
            "extract all frames from an animated image."
        ),
    )
    return parser


def _safe_write(data: ImageData, path: Path) -> None:
    """Write via a temp file so the target is never left in a partial state.

    Principle 8: on failure the source is untouched and no partial output
    is left behind.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=path.suffix, dir=path.parent)
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        write_image(data, tmp_path)
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    input_path: Path = args.input
    output_raw: str = args.output

    # ── validate input ──────────────────────────────────────────────
    if not input_path.exists():
        print(f"any2any: error: input file not found: {input_path}", file=sys.stderr)
        return 1
    if not input_path.is_file():
        print(f"any2any: error: input is not a file: {input_path}", file=sys.stderr)
        return 1

    in_ext = input_path.suffix.lower().lstrip(".")
    if not in_ext:
        print("any2any: error: input file has no extension", file=sys.stderr)
        return 1

    # ── detect multi-frame mode ("*.jpg") ───────────────────────────
    multi_frame = "*" in output_raw
    if multi_frame:
        out_ext = Path(output_raw).suffix.lower().lstrip(".")
    else:
        out_ext = Path(output_raw).suffix.lower().lstrip(".")

    if not out_ext:
        print("any2any: error: output has no extension", file=sys.stderr)
        return 1

    if not can_convert(in_ext, out_ext):
        print(
            f"any2any: error: no converter available for .{in_ext} -> .{out_ext}",
            file=sys.stderr,
        )
        return 1

    # ── read ────────────────────────────────────────────────────────
    try:
        data = read_image(input_path)
    except Exception as exc:
        print(f"any2any: error: failed to read input: {exc}", file=sys.stderr)
        return 1

    # ── write ───────────────────────────────────────────────────────
    try:
        if multi_frame:
            n = len(data.frames)
            width = len(str(n))
            for i, frame in enumerate(data.frames, 1):
                frame_path = Path(output_raw.replace("*", str(i).zfill(width)))
                single = ImageData(frames=[frame], metadata=data.metadata)
                _safe_write(single, frame_path)
            print(
                f"{input_path} -> {n} frame(s) as .{out_ext}",
                file=sys.stderr,
            )
        else:
            output_path = Path(output_raw)
            single = ImageData(frames=[data.frames[0]], metadata=data.metadata)
            _safe_write(single, output_path)
            print(f"{input_path} -> {output_path}", file=sys.stderr)
    except Exception as exc:
        print(f"any2any: error: conversion failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
