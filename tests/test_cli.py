"""Tests for the CLI interface."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from any2any.cli import main


# ── --version / --help ───────────────────────────────────────────────────


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["--version"])
    assert "any2any" in capsys.readouterr().out


def test_help_flag() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "any2any", "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "Convert files" in r.stdout


def test_module_entry_point() -> None:
    """python -m any2any with no args should fail with returncode 2."""
    r = subprocess.run(
        [sys.executable, "-m", "any2any"],
        capture_output=True, text=True,
    )
    assert r.returncode == 2


# ── input validation ─────────────────────────────────────────────────────


def test_missing_input(tmp_path: Path) -> None:
    assert main([str(tmp_path / "missing.png"), str(tmp_path / "o.jpg")]) == 1


def test_input_is_directory(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    d = tmp_path / "adir"
    d.mkdir()
    # directories have no extension, but even with one they aren't files
    assert main([str(d), str(tmp_path / "o.jpg")]) == 1
    assert "not a file" in capsys.readouterr().err


def test_no_input_extension(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "noext"
    f.write_bytes(b"x")
    assert main([str(f), str(tmp_path / "o.jpg")]) == 1
    assert "no extension" in capsys.readouterr().err


def test_no_output_extension(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "f.png"
    f.write_bytes(b"x")
    assert main([str(f), str(tmp_path / "noext")]) == 1
    assert "no extension" in capsys.readouterr().err


def test_unsupported_input_ext(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "f.xyz"
    f.write_bytes(b"x")
    assert main([str(f), str(tmp_path / "o.abc")]) == 1
    assert "no converter" in capsys.readouterr().err


def test_corrupt_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "bad.png"
    f.write_bytes(b"not an image at all")
    assert main([str(f), str(tmp_path / "o.jpg")]) == 1
    assert "error" in capsys.readouterr().err


# ── stderr progress messages ─────────────────────────────────────────────


def test_stderr_single_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "s.png"
    Image.new("RGB", (2, 2)).save(src)
    out = tmp_path / "o.jpg"
    assert main([str(src), str(out)]) == 0
    err = capsys.readouterr().err
    assert "->" in err
    assert "o.jpg" in err


def test_stderr_multi_frame(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "a.gif"
    frames = [Image.new("RGB", (2, 2), c) for c in ("red", "blue")]
    frames[0].save(src, save_all=True, append_images=frames[1:])
    assert main([str(src), str(tmp_path / "*.png")]) == 0
    err = capsys.readouterr().err
    assert "2 frame(s)" in err


# ── safe write (principle 8) ─────────────────────────────────────────────


def test_no_partial_output_on_read_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"broken")
    out = tmp_path / "out.jpg"
    assert main([str(bad), str(out)]) == 1
    assert not out.exists()


def test_source_unchanged_after_conversion(tmp_path: Path) -> None:
    src = tmp_path / "s.png"
    Image.new("RGB", (4, 4)).save(src)
    original = src.read_bytes()
    main([str(src), str(tmp_path / "o.jpg")])
    assert src.read_bytes() == original


def test_overwrite_existing_output(tmp_path: Path) -> None:
    """If the target already exists it should be replaced atomically."""
    src = tmp_path / "s.png"
    Image.new("RGB", (4, 4), "red").save(src)
    out = tmp_path / "o.jpg"
    out.write_bytes(b"stale")
    assert main([str(src), str(out)]) == 0
    assert out.stat().st_size > 5  # replaced, not the 5-byte stale content


# ── multi-frame star pattern ─────────────────────────────────────────────


def test_star_pattern_static_image(tmp_path: Path) -> None:
    """A static image with '*.png' should produce a single file '1.png'."""
    src = tmp_path / "s.png"
    Image.new("RGB", (2, 2)).save(src)
    assert main([str(src), str(tmp_path / "*.bmp")]) == 0
    assert (tmp_path / "1.bmp").exists()
    assert not (tmp_path / "2.bmp").exists()


def test_star_pattern_zero_padded(tmp_path: Path) -> None:
    """With >= 10 frames the filenames should be zero-padded."""
    src = tmp_path / "a.gif"
    # Use distinct RGB colours so Pillow doesn't collapse frames
    colors = [(i * 20, 0, 0) for i in range(12)]
    frames = [Image.new("RGB", (2, 2), c) for c in colors]
    frames[0].save(src, save_all=True, append_images=frames[1:], duration=50)
    assert main([str(src), str(tmp_path / "*.png")]) == 0
    assert (tmp_path / "01.png").exists()
    assert (tmp_path / "12.png").exists()


def test_star_pattern_subdirectory(tmp_path: Path) -> None:
    src = tmp_path / "s.gif"
    frames = [Image.new("RGB", (2, 2), c) for c in ("red", "blue")]
    frames[0].save(src, save_all=True, append_images=frames[1:])
    pattern = str(tmp_path / "sub" / "*.png")
    assert main([str(src), pattern]) == 0
    assert (tmp_path / "sub" / "1.png").exists()
