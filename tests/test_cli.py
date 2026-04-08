"""Tests for the CLI interface."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from any2any.cli import main


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["--version"])
    assert "any2any" in capsys.readouterr().out


def test_missing_input(tmp_path: Path) -> None:
    rc = main([str(tmp_path / "missing.png"), str(tmp_path / "out.jpg")])
    assert rc == 1


def test_no_input_extension(tmp_path: Path) -> None:
    infile = tmp_path / "noext"
    infile.write_bytes(b"data")
    rc = main([str(infile), str(tmp_path / "out.jpg")])
    assert rc == 1


def test_no_output_extension(tmp_path: Path) -> None:
    infile = tmp_path / "test.png"
    infile.write_bytes(b"data")
    rc = main([str(infile), str(tmp_path / "noext")])
    assert rc == 1


def test_unsupported_conversion(tmp_path: Path) -> None:
    infile = tmp_path / "file.xyz"
    infile.write_bytes(b"data")
    rc = main([str(infile), str(tmp_path / "out.abc")])
    assert rc == 1


def test_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "any2any", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Convert files" in result.stdout


def test_safe_write_no_partial_output(tmp_path: Path) -> None:
    """Principle 8: a failed conversion must not leave partial output."""
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not a real image")
    out = tmp_path / "out.jpg"
    rc = main([str(bad), str(out)])
    assert rc == 1
    assert not out.exists()
