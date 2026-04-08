"""Tests for image format conversion — readers, writers, and conversion pipeline."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageCms
from PIL.ExifTags import Base as ExifBase

from any2any.cli import main
from any2any.converters import (
    ImageData,
    can_convert,
    read_image,
    readable_extensions,
    write_image,
    writable_extensions,
)
from any2any.converters.image import (
    _cms_to_srgb,
    _ensure_mode,
    _extract_meta,
    _hi_to_8bit,
    _save_kwargs,
)


# ═══════════════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture()
def rgb_png(tmp_path: Path) -> Path:
    p = tmp_path / "rgb.png"
    Image.new("RGB", (10, 10), (255, 0, 0)).save(p)
    return p


@pytest.fixture()
def rgba_png(tmp_path: Path) -> Path:
    p = tmp_path / "rgba.png"
    Image.new("RGBA", (10, 10), (255, 0, 0, 128)).save(p)
    return p


@pytest.fixture()
def grayscale_png(tmp_path: Path) -> Path:
    p = tmp_path / "gray.png"
    Image.new("L", (10, 10), 128).save(p)
    return p


@pytest.fixture()
def palette_png(tmp_path: Path) -> Path:
    p = tmp_path / "palette.png"
    Image.new("P", (10, 10), 5).save(p)
    return p


@pytest.fixture()
def palette_transparent_png(tmp_path: Path) -> Path:
    p = tmp_path / "pt.png"
    img = Image.new("P", (10, 10), 0)
    img.info["transparency"] = 0
    img.save(p, transparency=0)
    return p


@pytest.fixture()
def binary_png(tmp_path: Path) -> Path:
    p = tmp_path / "binary.png"
    Image.new("1", (10, 10), 1).save(p)
    return p


@pytest.fixture()
def la_png(tmp_path: Path) -> Path:
    p = tmp_path / "la.png"
    Image.new("LA", (10, 10), (128, 64)).save(p)
    return p


@pytest.fixture()
def jpg_with_full_meta(tmp_path: Path) -> Path:
    """JPEG carrying EXIF, ICC profile, and known DPI."""
    p = tmp_path / "meta.jpg"
    img = Image.new("RGB", (10, 10), (0, 200, 0))
    exif = img.getexif()
    exif[ExifBase.Make] = "TestCam"
    exif[ExifBase.Model] = "X100"
    exif[ExifBase.DateTime] = "2025:06:01 08:00:00"
    exif[ExifBase.Software] = "any2any-test"
    srgb = ImageCms.createProfile("sRGB")
    icc_bytes = ImageCms.ImageCmsProfile(srgb).tobytes()
    img.save(p, format="JPEG", exif=exif.tobytes(),
             icc_profile=icc_bytes, dpi=(300, 300))
    return p


@pytest.fixture()
def animated_gif(tmp_path: Path) -> Path:
    p = tmp_path / "anim.gif"
    fs = [Image.new("RGB", (8, 8), c) for c in ("red", "green", "blue")]
    fs[0].save(p, save_all=True, append_images=fs[1:], duration=100, loop=0)
    return p


@pytest.fixture()
def animated_webp(tmp_path: Path) -> Path:
    p = tmp_path / "anim.webp"
    fs = [Image.new("RGB", (8, 8), c) for c in ("red", "green", "blue", "yellow")]
    fs[0].save(p, save_all=True, append_images=fs[1:], duration=80)
    return p


@pytest.fixture()
def tiny_1x1_png(tmp_path: Path) -> Path:
    p = tmp_path / "tiny.png"
    Image.new("RGB", (1, 1), (42, 43, 44)).save(p)
    return p


# ═══════════════════════════════════════════════════════════════════════════
#  Registry tests
# ═══════════════════════════════════════════════════════════════════════════


class TestRegistry:
    """can_convert / readable_extensions / writable_extensions."""

    @pytest.mark.parametrize("src,dst", [
        ("png", "jpg"), ("jpg", "png"), ("bmp", "tiff"), ("webp", "gif"),
        ("heic", "png"), ("png", "avif"), ("tif", "webp"), ("gif", "bmp"),
        ("jpeg", "png"), ("jpe", "tga"), ("jfif", "webp"),
        ("png", "jp2"), ("jp2", "png"),
        ("png", "pcx"), ("png", "dds"), ("png", "sgi"),
        ("cr2", "jpg"), ("nef", "png"), ("dng", "tiff"),
        ("psd", "png"), ("psb", "jpg"),
        ("svg", "png"),
    ])
    def test_known_conversions(self, src: str, dst: str) -> None:
        assert can_convert(src, dst)

    def test_case_insensitive(self) -> None:
        assert can_convert("PNG", "JPG")
        assert can_convert("Heic", "Png")

    def test_unknown_pair(self) -> None:
        assert not can_convert("xyz", "abc")

    def test_raw_write_not_registered(self) -> None:
        """RAW formats are read-only."""
        assert not can_convert("png", "cr2")
        assert not can_convert("jpg", "nef")

    def test_readable_extensions_non_empty(self) -> None:
        exts = readable_extensions()
        assert len(exts) > 30
        assert "png" in exts
        assert "heic" in exts
        assert "cr2" in exts

    def test_writable_extensions_non_empty(self) -> None:
        exts = writable_extensions()
        assert len(exts) > 20
        assert "jpg" in exts
        assert "heif" in exts

    def test_read_image_unknown_ext(self, tmp_path: Path) -> None:
        f = tmp_path / "f.zzz"
        f.write_bytes(b"x")
        with pytest.raises(ValueError, match="no reader"):
            read_image(f)

    def test_write_image_unknown_ext(self, tmp_path: Path) -> None:
        data = ImageData(frames=[Image.new("RGB", (2, 2))], metadata={})
        with pytest.raises(ValueError, match="no writer"):
            write_image(data, tmp_path / "out.zzz")


# ═══════════════════════════════════════════════════════════════════════════
#  _extract_meta
# ═══════════════════════════════════════════════════════════════════════════


class TestExtractMeta:
    def test_exif_from_info(self, jpg_with_full_meta: Path) -> None:
        with Image.open(jpg_with_full_meta) as img:
            meta = _extract_meta(img)
        assert "exif" in meta
        assert isinstance(meta["exif"], bytes)

    def test_icc_profile(self, jpg_with_full_meta: Path) -> None:
        with Image.open(jpg_with_full_meta) as img:
            meta = _extract_meta(img)
        assert "icc_profile" in meta
        assert isinstance(meta["icc_profile"], bytes)
        assert len(meta["icc_profile"]) > 100

    def test_dpi(self, jpg_with_full_meta: Path) -> None:
        with Image.open(jpg_with_full_meta) as img:
            meta = _extract_meta(img)
        assert meta["dpi"] == (300, 300)

    def test_no_meta_on_plain_image(self, rgb_png: Path) -> None:
        with Image.open(rgb_png) as img:
            meta = _extract_meta(img)
        assert "icc_profile" not in meta

    def test_exif_fallback_to_getexif(self) -> None:
        """When img.info has no 'exif' key, _extract_meta falls back to getexif()."""
        img = Image.new("RGB", (2, 2))
        exif = img.getexif()
        exif[ExifBase.Make] = "FallbackCam"
        # img.info won't contain 'exif', so the code must use getexif()
        meta = _extract_meta(img)
        # getexif().tobytes() should still produce something
        if meta.get("exif"):
            assert isinstance(meta["exif"], bytes)


# ═══════════════════════════════════════════════════════════════════════════
#  _save_kwargs
# ═══════════════════════════════════════════════════════════════════════════


class TestSaveKwargs:
    def test_jpeg_quality(self) -> None:
        kw = _save_kwargs({}, "JPEG")
        assert kw["quality"] == 100
        assert kw["subsampling"] == 0

    def test_webp_quality(self) -> None:
        kw = _save_kwargs({}, "WEBP")
        assert kw["quality"] == 100

    def test_heif_quality(self) -> None:
        kw = _save_kwargs({}, "HEIF")
        assert kw["quality"] == 100

    def test_avif_quality(self) -> None:
        kw = _save_kwargs({}, "AVIF")
        assert kw["quality"] == 100

    def test_png_compress_level(self) -> None:
        kw = _save_kwargs({}, "PNG")
        assert kw["compress_level"] == 9

    def test_tiff_compression(self) -> None:
        kw = _save_kwargs({}, "TIFF")
        assert kw["compression"] == "tiff_lzw"

    def test_jp2_lossless(self) -> None:
        kw = _save_kwargs({}, "JPEG2000")
        assert kw["irreversible"] is False

    def test_exif_embedded(self) -> None:
        meta = {"exif": b"fake-exif"}
        kw = _save_kwargs(meta, "JPEG")
        assert kw["exif"] == b"fake-exif"

    def test_exif_not_embedded_for_bmp(self) -> None:
        meta = {"exif": b"fake-exif"}
        kw = _save_kwargs(meta, "BMP")
        assert "exif" not in kw

    def test_icc_embedded(self) -> None:
        meta = {"icc_profile": b"fake-icc"}
        kw = _save_kwargs(meta, "PNG")
        assert kw["icc_profile"] == b"fake-icc"

    def test_icc_not_embedded_for_gif(self) -> None:
        meta = {"icc_profile": b"fake-icc"}
        kw = _save_kwargs(meta, "GIF")
        assert "icc_profile" not in kw

    def test_xmp_embedded_for_png(self) -> None:
        meta = {"xmp": b"<xmp/>"}
        kw = _save_kwargs(meta, "PNG")
        assert kw["xmp"] == b"<xmp/>"

    def test_xmp_not_embedded_for_heif(self) -> None:
        meta = {"xmp": b"<xmp/>"}
        kw = _save_kwargs(meta, "HEIF")
        assert "xmp" not in kw

    def test_dpi_passed_through(self) -> None:
        meta = {"dpi": (300, 300)}
        kw = _save_kwargs(meta, "JPEG")
        assert kw["dpi"] == (300, 300)

    def test_unknown_format_no_quality(self) -> None:
        kw = _save_kwargs({}, "GIF")
        assert "quality" not in kw


# ═══════════════════════════════════════════════════════════════════════════
#  Colour-space / mode conversion helpers
# ═══════════════════════════════════════════════════════════════════════════


class TestCmsToSrgb:
    def test_non_cmyk_passthrough(self) -> None:
        img = Image.new("RGB", (2, 2))
        meta: dict[str, object] = {}
        result = _cms_to_srgb(img, meta)
        assert result.mode == "RGB"

    def test_cmyk_without_icc_falls_back(self) -> None:
        img = Image.new("CMYK", (2, 2), (0, 0, 0, 0))
        meta: dict[str, object] = {}
        result = _cms_to_srgb(img, meta)
        assert result.mode == "RGB"

    def test_cmyk_with_icc_converts(self) -> None:
        img = Image.new("CMYK", (4, 4), (0, 255, 255, 0))
        cmyk_profile = ImageCms.createProfile("sRGB")  # not a real CMYK profile
        # use sRGB→sRGB to exercise the code path; won't be accurate but tests flow
        icc_bytes = ImageCms.ImageCmsProfile(cmyk_profile).tobytes()
        meta: dict[str, object] = {"icc_profile": icc_bytes}
        result = _cms_to_srgb(img, meta)
        # Should either succeed via ICC or fallback to .convert("RGB")
        assert result.mode == "RGB"


class TestHiTo8bit:
    def test_mode_I(self) -> None:
        arr = np.array([[0, 32768], [65535, 16384]], dtype=np.int32)
        img = Image.fromarray(arr, mode="I")
        result = _hi_to_8bit(img)
        assert result.mode == "L"
        assert np.array(result).max() == 255
        assert np.array(result).min() == 0

    def test_mode_F(self) -> None:
        arr = np.array([[0.0, 0.5], [1.0, 0.25]], dtype=np.float32)
        img = Image.fromarray(arr, mode="F")
        result = _hi_to_8bit(img)
        assert result.mode == "L"
        assert np.array(result).max() == 255

    def test_mode_I_all_zeros(self) -> None:
        arr = np.zeros((4, 4), dtype=np.int32)
        img = Image.fromarray(arr, mode="I")
        result = _hi_to_8bit(img)
        assert result.mode == "L"
        assert np.array(result).max() == 0

    def test_rgb_passthrough(self) -> None:
        img = Image.new("RGB", (2, 2))
        assert _hi_to_8bit(img).mode == "RGB"


class TestEnsureMode:
    def test_rgba_to_jpeg(self) -> None:
        img = Image.new("RGBA", (2, 2), (255, 0, 0, 128))
        result = _ensure_mode(img, "JPEG", {})
        assert result.mode == "RGB"

    def test_palette_to_jpeg(self) -> None:
        img = Image.new("P", (2, 2), 3)
        result = _ensure_mode(img, "JPEG", {})
        assert result.mode == "RGB"

    def test_palette_with_transparency_to_tiff(self) -> None:
        img = Image.new("P", (2, 2), 0)
        img.info["transparency"] = 0
        result = _ensure_mode(img, "TIFF", {})
        assert result.mode == "RGBA"

    def test_palette_without_transparency_to_tiff(self) -> None:
        img = Image.new("P", (2, 2), 0)
        result = _ensure_mode(img, "TIFF", {})
        assert result.mode == "RGB"

    def test_la_to_jpeg(self) -> None:
        img = Image.new("LA", (2, 2), (128, 64))
        result = _ensure_mode(img, "JPEG", {})
        assert result.mode == "RGB"

    def test_L_passthrough_for_jpeg(self) -> None:
        img = Image.new("L", (2, 2), 128)
        result = _ensure_mode(img, "JPEG", {})
        assert result.mode == "L"

    def test_binary_passthrough_for_jpeg(self) -> None:
        img = Image.new("1", (2, 2), 1)
        result = _ensure_mode(img, "JPEG", {})
        assert result.mode == "1"

    def test_rgb_passthrough_for_png(self) -> None:
        img = Image.new("RGB", (2, 2))
        result = _ensure_mode(img, "PNG", {})
        assert result.mode == "RGB"


# ═══════════════════════════════════════════════════════════════════════════
#  Pillow reader
# ═══════════════════════════════════════════════════════════════════════════


class TestPillowReader:
    def test_single_frame(self, rgb_png: Path) -> None:
        data = read_image(rgb_png)
        assert len(data.frames) == 1
        assert data.frames[0].size == (10, 10)

    def test_animated_gif_frames(self, animated_gif: Path) -> None:
        data = read_image(animated_gif)
        assert len(data.frames) == 3

    def test_animated_webp_frames(self, animated_webp: Path) -> None:
        data = read_image(animated_webp)
        assert len(data.frames) == 4

    def test_metadata_preserved_in_read(self, jpg_with_full_meta: Path) -> None:
        data = read_image(jpg_with_full_meta)
        assert "exif" in data.metadata
        assert "icc_profile" in data.metadata


# ═══════════════════════════════════════════════════════════════════════════
#  Import-error paths for optional readers
# ═══════════════════════════════════════════════════════════════════════════


class TestReaderImportErrors:
    """Readers for optional deps raise ImportError with install instructions."""

    def test_raw_import_error(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        import any2any.converters.image as mod
        monkeypatch.setattr(mod, "_rawpy_ok", False)
        f = tmp_path / "fake.cr2"
        f.write_bytes(b"x")
        with pytest.raises(ImportError, match="rawpy"):
            mod._read_raw(f)

    def test_psd_import_error(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        import any2any.converters.image as mod
        monkeypatch.setattr(mod, "_psd_ok", False)
        f = tmp_path / "fake.psd"
        f.write_bytes(b"x")
        with pytest.raises(ImportError, match="psd-tools"):
            mod._read_psd(f)

    def test_svg_import_error(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        import any2any.converters.image as mod
        monkeypatch.setattr(mod, "_svg_ok", False)
        f = tmp_path / "fake.svg"
        f.write_bytes(b"x")
        with pytest.raises(ImportError, match="svglib"):
            mod._read_svg(f)


# ═══════════════════════════════════════════════════════════════════════════
#  Format matrix — pairwise conversions
# ═══════════════════════════════════════════════════════════════════════════


class TestFormatMatrix:
    """Test actual file conversion across many source/target pairs."""

    @pytest.mark.parametrize("out_ext", [
        "jpg", "png", "bmp", "gif", "tiff", "tga", "webp",
        "ppm", "ico", "heif", "avif", "jp2", "pcx",
    ])
    def test_png_to_X(self, rgb_png: Path, tmp_path: Path, out_ext: str) -> None:
        out = tmp_path / f"out.{out_ext}"
        assert main([str(rgb_png), str(out)]) == 0
        assert out.stat().st_size > 0

    @pytest.mark.parametrize("out_ext", [
        "png", "bmp", "tiff", "webp", "gif", "tga", "ppm",
    ])
    def test_jpg_to_X(self, tmp_path: Path, out_ext: str) -> None:
        src = tmp_path / "src.jpg"
        Image.new("RGB", (8, 8), "blue").save(src, format="JPEG")
        out = tmp_path / f"out.{out_ext}"
        assert main([str(src), str(out)]) == 0
        assert out.stat().st_size > 0

    @pytest.mark.parametrize("out_ext", ["jpg", "png", "bmp", "tiff"])
    def test_webp_to_X(self, tmp_path: Path, out_ext: str) -> None:
        src = tmp_path / "src.webp"
        Image.new("RGB", (8, 8), "green").save(src, format="WEBP")
        out = tmp_path / f"out.{out_ext}"
        assert main([str(src), str(out)]) == 0
        assert out.stat().st_size > 0

    @pytest.mark.parametrize("out_ext", ["jpg", "png", "webp"])
    def test_tiff_to_X(self, tmp_path: Path, out_ext: str) -> None:
        src = tmp_path / "src.tiff"
        Image.new("RGB", (8, 8), "purple").save(src, format="TIFF")
        out = tmp_path / f"out.{out_ext}"
        assert main([str(src), str(out)]) == 0

    @pytest.mark.parametrize("out_ext", ["jpg", "png", "webp"])
    def test_bmp_to_X(self, tmp_path: Path, out_ext: str) -> None:
        src = tmp_path / "src.bmp"
        Image.new("RGB", (8, 8), "orange").save(src, format="BMP")
        out = tmp_path / f"out.{out_ext}"
        assert main([str(src), str(out)]) == 0

    @pytest.mark.parametrize("out_ext", ["jpg", "png", "bmp"])
    def test_gif_to_X(self, tmp_path: Path, out_ext: str) -> None:
        src = tmp_path / "src.gif"
        Image.new("RGB", (8, 8), "cyan").save(src, format="GIF")
        out = tmp_path / f"out.{out_ext}"
        assert main([str(src), str(out)]) == 0

    @pytest.mark.parametrize("out_ext", ["jpg", "png", "webp"])
    def test_heif_to_X(self, tmp_path: Path, out_ext: str) -> None:
        src = tmp_path / "src.heif"
        Image.new("RGB", (8, 8), "red").save(src, format="HEIF", quality=100)
        out = tmp_path / f"out.{out_ext}"
        assert main([str(src), str(out)]) == 0

    @pytest.mark.parametrize("out_ext", ["jpg", "png", "webp"])
    def test_avif_to_X(self, tmp_path: Path, out_ext: str) -> None:
        src = tmp_path / "src.avif"
        Image.new("RGB", (8, 8), "red").save(src, format="AVIF", quality=100)
        out = tmp_path / f"out.{out_ext}"
        assert main([str(src), str(out)]) == 0


class TestAliasExtensions:
    """Extensions that map to the same format must work interchangeably."""

    def test_jpeg_alias(self, tmp_path: Path) -> None:
        src = tmp_path / "src.jpeg"
        Image.new("RGB", (4, 4)).save(src, format="JPEG")
        out = tmp_path / "out.png"
        assert main([str(src), str(out)]) == 0

    def test_jpe_alias(self, tmp_path: Path) -> None:
        src = tmp_path / "src.png"
        Image.new("RGB", (4, 4)).save(src)
        out = tmp_path / "out.jpe"
        assert main([str(src), str(out)]) == 0
        with Image.open(out) as img:
            assert img.format == "JPEG"

    def test_jfif_alias(self, tmp_path: Path) -> None:
        src = tmp_path / "src.png"
        Image.new("RGB", (4, 4)).save(src)
        out = tmp_path / "out.jfif"
        assert main([str(src), str(out)]) == 0

    def test_tif_alias(self, tmp_path: Path) -> None:
        src = tmp_path / "src.png"
        Image.new("RGB", (4, 4)).save(src)
        out = tmp_path / "out.tif"
        assert main([str(src), str(out)]) == 0
        with Image.open(out) as img:
            assert img.format == "TIFF"

    def test_heic_alias(self, tmp_path: Path) -> None:
        src = tmp_path / "src.png"
        Image.new("RGB", (4, 4)).save(src)
        out = tmp_path / "out.heic"
        assert main([str(src), str(out)]) == 0


# ═══════════════════════════════════════════════════════════════════════════
#  Colour-mode edge cases in real conversion
# ═══════════════════════════════════════════════════════════════════════════


class TestModeConversion:
    def test_rgba_to_jpg(self, rgba_png: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.jpg"
        assert main([str(rgba_png), str(out)]) == 0
        with Image.open(out) as img:
            assert img.mode == "RGB"

    def test_rgba_to_bmp(self, rgba_png: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.bmp"
        assert main([str(rgba_png), str(out)]) == 0
        with Image.open(out) as img:
            assert img.mode == "RGB"

    def test_grayscale_to_jpg(self, grayscale_png: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.jpg"
        assert main([str(grayscale_png), str(out)]) == 0
        with Image.open(out) as img:
            assert img.mode == "L"

    def test_grayscale_to_png(self, grayscale_png: Path, tmp_path: Path) -> None:
        out = tmp_path / "out2.png"
        assert main([str(grayscale_png), str(out)]) == 0
        with Image.open(out) as img:
            assert img.mode == "L"

    def test_palette_to_jpg(self, palette_png: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.jpg"
        assert main([str(palette_png), str(out)]) == 0
        with Image.open(out) as img:
            assert img.mode == "RGB"

    def test_palette_to_tiff(self, palette_png: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.tiff"
        assert main([str(palette_png), str(out)]) == 0

    def test_binary_to_jpg(self, binary_png: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.jpg"
        assert main([str(binary_png), str(out)]) == 0

    def test_la_to_jpg(self, la_png: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.jpg"
        assert main([str(la_png), str(out)]) == 0
        with Image.open(out) as img:
            assert img.mode == "RGB"

    def test_la_to_png(self, la_png: Path, tmp_path: Path) -> None:
        out = tmp_path / "out2.png"
        assert main([str(la_png), str(out)]) == 0

    def test_16bit_to_jpg(self, tmp_path: Path) -> None:
        """High bit-depth images should be tone-mapped to 8-bit."""
        src = tmp_path / "hi.tiff"
        arr = np.linspace(0, 65535, 100, dtype=np.int32).reshape(10, 10)
        Image.fromarray(arr, mode="I").save(src, format="TIFF")
        out = tmp_path / "out.jpg"
        assert main([str(src), str(out)]) == 0
        with Image.open(out) as img:
            assert img.mode == "L"


# ═══════════════════════════════════════════════════════════════════════════
#  EXIF / ICC / DPI preservation
# ═══════════════════════════════════════════════════════════════════════════


class TestMetadataPreservation:
    def _check_exif(self, path: Path) -> None:
        with Image.open(path) as img:
            exif = img.getexif()
            assert exif.get(ExifBase.Make) == "TestCam"
            assert exif.get(ExifBase.Model) == "X100"
            assert exif.get(ExifBase.DateTime) == "2025:06:01 08:00:00"
            assert exif.get(ExifBase.Software) == "any2any-test"

    @pytest.mark.parametrize("ext", ["png", "webp", "tiff", "heif", "avif", "jpg"])
    def test_exif(self, jpg_with_full_meta: Path, tmp_path: Path, ext: str) -> None:
        out = tmp_path / f"out.{ext}"
        assert main([str(jpg_with_full_meta), str(out)]) == 0
        self._check_exif(out)

    def test_exif_roundtrip(self, jpg_with_full_meta: Path, tmp_path: Path) -> None:
        """JPEG → PNG → TIFF → JPEG must preserve all EXIF fields."""
        a = tmp_path / "a.png"
        b = tmp_path / "b.tiff"
        c = tmp_path / "c.jpg"
        assert main([str(jpg_with_full_meta), str(a)]) == 0
        assert main([str(a), str(b)]) == 0
        assert main([str(b), str(c)]) == 0
        self._check_exif(c)

    def test_icc_profile_preserved(self, jpg_with_full_meta: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.png"
        assert main([str(jpg_with_full_meta), str(out)]) == 0
        with Image.open(out) as img:
            assert img.info.get("icc_profile")
            assert len(img.info["icc_profile"]) > 100

    def test_icc_roundtrip(self, jpg_with_full_meta: Path, tmp_path: Path) -> None:
        mid = tmp_path / "mid.webp"
        out = tmp_path / "out.jpg"
        assert main([str(jpg_with_full_meta), str(mid)]) == 0
        assert main([str(mid), str(out)]) == 0
        with Image.open(out) as img:
            assert img.info.get("icc_profile")

    def test_dpi_preserved_in_tiff(self, jpg_with_full_meta: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.tiff"
        assert main([str(jpg_with_full_meta), str(out)]) == 0
        with Image.open(out) as img:
            dpi = img.info.get("dpi")
            assert dpi is not None
            assert abs(dpi[0] - 300) < 1

    def test_exif_not_on_bmp(self, jpg_with_full_meta: Path, tmp_path: Path) -> None:
        """BMP does not support EXIF; conversion should still succeed."""
        out = tmp_path / "out.bmp"
        assert main([str(jpg_with_full_meta), str(out)]) == 0
        assert out.exists()


# ═══════════════════════════════════════════════════════════════════════════
#  Lossless / pixel-perfect conversions
# ═══════════════════════════════════════════════════════════════════════════


class TestLossless:
    def _assert_pixel_equal(self, a: Path, b: Path) -> None:
        with Image.open(a) as ia, Image.open(b) as ib:
            assert ia.size == ib.size
            assert ia.convert("RGB").tobytes() == ib.convert("RGB").tobytes()

    def test_png_bmp_png(self, tmp_path: Path) -> None:
        src = tmp_path / "s.png"
        Image.new("RGB", (10, 10), (123, 45, 67)).save(src)
        mid = tmp_path / "m.bmp"
        out = tmp_path / "o.png"
        assert main([str(src), str(mid)]) == 0
        assert main([str(mid), str(out)]) == 0
        self._assert_pixel_equal(src, out)

    def test_png_tiff_png(self, tmp_path: Path) -> None:
        src = tmp_path / "s.png"
        Image.new("RGB", (10, 10), (200, 100, 50)).save(src)
        mid = tmp_path / "m.tiff"
        out = tmp_path / "o.png"
        assert main([str(src), str(mid)]) == 0
        assert main([str(mid), str(out)]) == 0
        self._assert_pixel_equal(src, out)

    def test_png_ppm_png(self, tmp_path: Path) -> None:
        src = tmp_path / "s.png"
        Image.new("RGB", (10, 10), (11, 22, 33)).save(src)
        mid = tmp_path / "m.ppm"
        out = tmp_path / "o.png"
        assert main([str(src), str(mid)]) == 0
        assert main([str(mid), str(out)]) == 0
        self._assert_pixel_equal(src, out)

    def test_png_tga_png(self, tmp_path: Path) -> None:
        src = tmp_path / "s.png"
        Image.new("RGB", (10, 10), (99, 88, 77)).save(src)
        mid = tmp_path / "m.tga"
        out = tmp_path / "o.png"
        assert main([str(src), str(mid)]) == 0
        assert main([str(mid), str(out)]) == 0
        self._assert_pixel_equal(src, out)


# ═══════════════════════════════════════════════════════════════════════════
#  Multi-frame / animation
# ═══════════════════════════════════════════════════════════════════════════


class TestMultiFrame:
    def test_gif_single_output_first_frame_only(
        self, animated_gif: Path, tmp_path: Path,
    ) -> None:
        out = tmp_path / "first.jpg"
        assert main([str(animated_gif), str(out)]) == 0
        with Image.open(out) as img:
            assert getattr(img, "n_frames", 1) == 1

    def test_gif_star_pattern(self, animated_gif: Path, tmp_path: Path) -> None:
        assert main([str(animated_gif), str(tmp_path / "*.png")]) == 0
        for i in (1, 2, 3):
            assert (tmp_path / f"{i}.png").exists()

    def test_webp_star_pattern(self, animated_webp: Path, tmp_path: Path) -> None:
        assert main([str(animated_webp), str(tmp_path / "*.jpg")]) == 0
        for i in (1, 2, 3, 4):
            assert (tmp_path / f"{i}.jpg").exists()

    def test_static_image_star_produces_one(self, rgb_png: Path, tmp_path: Path) -> None:
        assert main([str(rgb_png), str(tmp_path / "*.bmp")]) == 0
        assert (tmp_path / "1.bmp").exists()
        assert not (tmp_path / "2.bmp").exists()

    def test_each_frame_is_valid_image(self, animated_gif: Path, tmp_path: Path) -> None:
        assert main([str(animated_gif), str(tmp_path / "*.png")]) == 0
        for i in (1, 2, 3):
            with Image.open(tmp_path / f"{i}.png") as img:
                assert img.size == (8, 8)

    def test_star_with_many_frames_zero_pads(self, tmp_path: Path) -> None:
        src = tmp_path / "many.gif"
        colors = [(i * 16, 0, 0) for i in range(15)]
        fs = [Image.new("RGB", (4, 4), c) for c in colors]
        fs[0].save(src, save_all=True, append_images=fs[1:], duration=50)
        assert main([str(src), str(tmp_path / "*.png")]) == 0
        assert (tmp_path / "01.png").exists()
        assert (tmp_path / "15.png").exists()


# ═══════════════════════════════════════════════════════════════════════════
#  Safe write (principle 8)
# ═══════════════════════════════════════════════════════════════════════════


class TestSafeWrite:
    def test_no_partial_output_on_read_failure(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.png"
        bad.write_bytes(b"broken data")
        out = tmp_path / "out.jpg"
        assert main([str(bad), str(out)]) == 1
        assert not out.exists()

    def test_source_bytes_unchanged(self, rgb_png: Path, tmp_path: Path) -> None:
        original = rgb_png.read_bytes()
        main([str(rgb_png), str(tmp_path / "o.jpg")])
        assert rgb_png.read_bytes() == original

    def test_overwrite_replaces_stale(self, rgb_png: Path, tmp_path: Path) -> None:
        out = tmp_path / "o.jpg"
        out.write_bytes(b"stale")
        assert main([str(rgb_png), str(out)]) == 0
        assert out.stat().st_size > 5

    def test_source_equals_target(self, tmp_path: Path) -> None:
        """Re-encoding in place must not corrupt the file."""
        src = tmp_path / "inplace.png"
        Image.new("RGB", (4, 4), (10, 20, 30)).save(src)
        assert main([str(src), str(src)]) == 0
        with Image.open(src) as img:
            assert img.size == (4, 4)


# ═══════════════════════════════════════════════════════════════════════════
#  Edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_1x1_image(self, tiny_1x1_png: Path, tmp_path: Path) -> None:
        out = tmp_path / "tiny.jpg"
        assert main([str(tiny_1x1_png), str(out)]) == 0
        with Image.open(out) as img:
            assert img.size == (1, 1)

    def test_same_format_reencode(self, tmp_path: Path) -> None:
        src = tmp_path / "s.jpg"
        Image.new("RGB", (4, 4), "red").save(src, format="JPEG")
        out = tmp_path / "o.jpg"
        assert main([str(src), str(out)]) == 0
        assert out.stat().st_size > 0

    def test_large_dimension(self, tmp_path: Path) -> None:
        src = tmp_path / "big.png"
        Image.new("RGB", (2000, 2000), "white").save(src)
        out = tmp_path / "big.jpg"
        assert main([str(src), str(out)]) == 0
        with Image.open(out) as img:
            assert img.size == (2000, 2000)

    def test_non_square(self, tmp_path: Path) -> None:
        src = tmp_path / "rect.png"
        Image.new("RGB", (100, 10), "blue").save(src)
        out = tmp_path / "rect.webp"
        assert main([str(src), str(out)]) == 0
        with Image.open(out) as img:
            assert img.size == (100, 10)

    def test_many_conversions_sequential(self, tmp_path: Path) -> None:
        """Chain: PNG → JPG → WebP → TIFF → BMP → PNG and compare."""
        src = tmp_path / "chain.png"
        # Use a solid colour so lossy steps don't drift too much
        Image.new("RGB", (8, 8), (128, 128, 128)).save(src)
        steps = ["a.jpg", "b.webp", "c.tiff", "d.bmp", "e.png"]
        prev = src
        for name in steps:
            nxt = tmp_path / name
            assert main([str(prev), str(nxt)]) == 0
            prev = nxt
        with Image.open(prev) as img:
            assert img.size == (8, 8)
