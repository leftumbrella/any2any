"""Tests for image format conversion."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from PIL.ExifTags import Base as ExifBase

from any2any.cli import main
from any2any.converters import can_convert, read_image


# ── fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture()
def png_file(tmp_path: Path) -> Path:
    path = tmp_path / "test.png"
    Image.new("RGB", (10, 10), color=(255, 0, 0)).save(path, format="PNG")
    return path


@pytest.fixture()
def rgba_png_file(tmp_path: Path) -> Path:
    path = tmp_path / "test_rgba.png"
    Image.new("RGBA", (10, 10), color=(255, 0, 0, 128)).save(path, format="PNG")
    return path


@pytest.fixture()
def jpg_with_exif(tmp_path: Path) -> Path:
    path = tmp_path / "exif.jpg"
    img = Image.new("RGB", (10, 10), color=(0, 255, 0))
    exif = img.getexif()
    exif[ExifBase.Make] = "TestCamera"
    exif[ExifBase.Model] = "TestModel"
    exif[ExifBase.DateTime] = "2025:01:15 12:30:00"
    img.save(path, format="JPEG", exif=exif.tobytes())
    return path


@pytest.fixture()
def animated_gif(tmp_path: Path) -> Path:
    path = tmp_path / "anim.gif"
    frames = [
        Image.new("RGB", (10, 10), color=(255, 0, 0)),
        Image.new("RGB", (10, 10), color=(0, 255, 0)),
        Image.new("RGB", (10, 10), color=(0, 0, 255)),
    ]
    frames[0].save(
        path, save_all=True, append_images=frames[1:], duration=100, loop=0,
    )
    return path


# ── registry ─────────────────────────────────────────────────────────────


class TestRegistry:
    def test_png_jpg(self) -> None:
        assert can_convert("png", "jpg")

    def test_jpg_png(self) -> None:
        assert can_convert("jpg", "png")

    def test_heic_png(self) -> None:
        assert can_convert("heic", "png")

    def test_png_avif(self) -> None:
        assert can_convert("png", "avif")

    def test_raw_readable(self) -> None:
        assert can_convert("cr2", "jpg")

    def test_psd_readable(self) -> None:
        assert can_convert("psd", "png")

    def test_svg_readable(self) -> None:
        assert can_convert("svg", "png")

    def test_unknown(self) -> None:
        assert not can_convert("xyz", "abc")

    def test_case_insensitive(self) -> None:
        assert can_convert("PNG", "JPG")


# ── basic conversions ────────────────────────────────────────────────────


class TestConversion:
    @pytest.mark.parametrize(
        "out_name",
        [
            "out.jpg", "out.webp", "out.bmp", "out.gif", "out.tiff",
            "out.tga", "out.ppm", "out.ico", "out.heif", "out.avif",
        ],
    )
    def test_png_to_format(self, png_file: Path, tmp_path: Path, out_name: str) -> None:
        out = tmp_path / out_name
        assert main([str(png_file), str(out)]) == 0
        assert out.exists()

    def test_png_to_jp2(self, png_file: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.jp2"
        assert main([str(png_file), str(out)]) == 0
        assert out.exists()

    def test_rgba_to_jpg(self, rgba_png_file: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.jpg"
        assert main([str(rgba_png_file), str(out)]) == 0
        with Image.open(out) as img:
            assert img.mode == "RGB"

    def test_same_format_reencode(self, png_file: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.png"
        assert main([str(png_file), str(out)]) == 0
        assert out.exists()

    def test_output_subdir_created(self, png_file: Path, tmp_path: Path) -> None:
        out = tmp_path / "sub" / "dir" / "out.jpg"
        assert main([str(png_file), str(out)]) == 0
        assert out.exists()

    def test_roundtrip_heif(self, png_file: Path, tmp_path: Path) -> None:
        heif = tmp_path / "mid.heif"
        out = tmp_path / "final.png"
        assert main([str(png_file), str(heif)]) == 0
        assert main([str(heif), str(out)]) == 0
        with Image.open(out) as img:
            assert img.size == (10, 10)

    def test_roundtrip_avif(self, png_file: Path, tmp_path: Path) -> None:
        avif = tmp_path / "mid.avif"
        out = tmp_path / "final.png"
        assert main([str(png_file), str(avif)]) == 0
        assert main([str(avif), str(out)]) == 0
        with Image.open(out) as img:
            assert img.size == (10, 10)


# ── EXIF preservation ────────────────────────────────────────────────────


class TestExif:
    def _check(self, path: Path) -> None:
        with Image.open(path) as img:
            exif = img.getexif()
            assert exif.get(ExifBase.Make) == "TestCamera"
            assert exif.get(ExifBase.Model) == "TestModel"
            assert exif.get(ExifBase.DateTime) == "2025:01:15 12:30:00"

    @pytest.mark.parametrize("ext", ["png", "webp", "tiff", "heif", "avif", "jpg"])
    def test_exif_preserved(self, jpg_with_exif: Path, tmp_path: Path, ext: str) -> None:
        out = tmp_path / f"out.{ext}"
        assert main([str(jpg_with_exif), str(out)]) == 0
        self._check(out)

    def test_roundtrip_exif(self, jpg_with_exif: Path, tmp_path: Path) -> None:
        mid = tmp_path / "mid.png"
        out = tmp_path / "final.jpg"
        assert main([str(jpg_with_exif), str(mid)]) == 0
        assert main([str(mid), str(out)]) == 0
        self._check(out)


# ── lossless quality ─────────────────────────────────────────────────────


class TestLossless:
    def test_png_tiff_png(self, tmp_path: Path) -> None:
        src = tmp_path / "src.png"
        Image.new("RGB", (10, 10), color=(123, 45, 67)).save(src)
        mid = tmp_path / "mid.tiff"
        out = tmp_path / "final.png"
        assert main([str(src), str(mid)]) == 0
        assert main([str(mid), str(out)]) == 0
        with Image.open(src) as a, Image.open(out) as b:
            assert list(a.getdata()) == list(b.getdata())

    def test_png_bmp(self, tmp_path: Path) -> None:
        src = tmp_path / "src.png"
        Image.new("RGB", (10, 10), color=(200, 100, 50)).save(src)
        out = tmp_path / "out.bmp"
        assert main([str(src), str(out)]) == 0
        with Image.open(src) as a, Image.open(out) as b:
            assert list(a.getdata()) == list(b.getdata())


# ── multi-frame / animation ─────────────────────────────────────────────


class TestMultiFrame:
    def test_single_output_first_frame(self, animated_gif: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.jpg"
        assert main([str(animated_gif), str(out)]) == 0
        assert out.exists()

    def test_star_pattern_all_frames(self, animated_gif: Path, tmp_path: Path) -> None:
        pattern = str(tmp_path / "*.png")
        assert main([str(animated_gif), pattern]) == 0
        assert (tmp_path / "1.png").exists()
        assert (tmp_path / "2.png").exists()
        assert (tmp_path / "3.png").exists()

    def test_frame_count(self, animated_gif: Path) -> None:
        data = read_image(animated_gif)
        assert len(data.frames) == 3


# ── safe write ───────────────────────────────────────────────────────────


class TestSafeWrite:
    def test_no_partial_output(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.png"
        bad.write_bytes(b"not a real image")
        out = tmp_path / "out.jpg"
        assert main([str(bad), str(out)]) == 1
        assert not out.exists()

    def test_source_unchanged(self, tmp_path: Path) -> None:
        src = tmp_path / "src.png"
        Image.new("RGB", (10, 10)).save(src)
        original = src.read_bytes()
        out = tmp_path / "out.jpg"
        main([str(src), str(out)])
        assert src.read_bytes() == original
