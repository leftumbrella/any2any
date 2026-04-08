"""Functional tests using real test assets (tests/assests/heic.HEIC, gif.gif).

All intermediate / output files are written to pytest's tmp_path and
cleaned up automatically.  The two source assets are NEVER modified.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from PIL.ExifTags import Base as ExifBase

from any2any.cli import main
from any2any.converters import read_image

# ── locate assets relative to this file ──────────────────────────────────

_ASSETS = Path(__file__).resolve().parent / "assests"
_HEIC = _ASSETS / "heic.HEIC"
_GIF = _ASSETS / "gif.gif"


@pytest.fixture(autouse=True)
def _check_assets() -> None:
    """Skip the entire module if the test assets are missing."""
    if not _HEIC.exists() or not _GIF.exists():
        pytest.skip("test assets not found in tests/assests/")


# ═══════════════════════════════════════════════════════════════════════════
#  HEIC source — basic conversion to every writable raster format
# ═══════════════════════════════════════════════════════════════════════════


class TestHeicToFormats:
    """Convert the real HEIC photo to many target formats."""

    @pytest.mark.parametrize("ext", [
        "jpg", "jpeg", "jpe", "jfif",
        "png",
        "bmp",
        "gif",
        "tiff", "tif",
        "webp",
        "avif",
        "heif",
        "tga",
        "ppm",
        "ico",
        "jp2",
        "pcx",
    ])
    def test_heic_to_format(self, tmp_path: Path, ext: str) -> None:
        out = tmp_path / f"heic_out.{ext}"
        assert main([str(_HEIC), str(out)]) == 0
        assert out.exists()
        assert out.stat().st_size > 0

    def test_heic_to_jpg_is_valid_jpeg(self, tmp_path: Path) -> None:
        out = tmp_path / "photo.jpg"
        assert main([str(_HEIC), str(out)]) == 0
        with Image.open(out) as img:
            assert img.format == "JPEG"
            assert img.mode == "RGB"
            assert img.size[0] > 0 and img.size[1] > 0

    def test_heic_to_png_preserves_dimensions(self, tmp_path: Path) -> None:
        out = tmp_path / "photo.png"
        assert main([str(_HEIC), str(out)]) == 0
        data_src = read_image(_HEIC)
        with Image.open(out) as img:
            assert img.size == data_src.frames[0].size

    def test_heic_to_webp_valid(self, tmp_path: Path) -> None:
        out = tmp_path / "photo.webp"
        assert main([str(_HEIC), str(out)]) == 0
        with Image.open(out) as img:
            assert img.format == "WEBP"

    def test_heic_to_tiff_valid(self, tmp_path: Path) -> None:
        out = tmp_path / "photo.tiff"
        assert main([str(_HEIC), str(out)]) == 0
        with Image.open(out) as img:
            assert img.format == "TIFF"

    def test_heic_to_avif_valid(self, tmp_path: Path) -> None:
        out = tmp_path / "photo.avif"
        assert main([str(_HEIC), str(out)]) == 0
        with Image.open(out) as img:
            assert img.format == "AVIF"

    def test_heic_to_bmp_valid(self, tmp_path: Path) -> None:
        out = tmp_path / "photo.bmp"
        assert main([str(_HEIC), str(out)]) == 0
        with Image.open(out) as img:
            assert img.format == "BMP"
            assert img.mode == "RGB"


# ═══════════════════════════════════════════════════════════════════════════
#  HEIC — EXIF / metadata preservation
# ═══════════════════════════════════════════════════════════════════════════


class TestHeicExif:
    """The real HEIC should carry EXIF; verify it survives conversion."""

    @pytest.fixture()
    def src_meta(self) -> dict[str, object]:
        data = read_image(_HEIC)
        return data.metadata

    def test_heic_has_exif(self, src_meta: dict[str, object]) -> None:
        assert "exif" in src_meta, "source HEIC should contain EXIF data"

    @pytest.mark.parametrize("ext", ["jpg", "png", "webp", "tiff", "avif", "heif"])
    def test_exif_preserved(self, tmp_path: Path, ext: str) -> None:
        out = tmp_path / f"exif_out.{ext}"
        assert main([str(_HEIC), str(out)]) == 0
        with Image.open(out) as img:
            exif = img.getexif()
            # A real photo should have at least one common EXIF tag
            has_any = any(
                exif.get(tag)
                for tag in (ExifBase.Make, ExifBase.Model, ExifBase.DateTime,
                            ExifBase.ExifVersion, ExifBase.ImageWidth)
            )
            assert has_any, f"EXIF lost during HEIC → .{ext}"

    def test_exif_roundtrip_heic_jpg_png_jpg(self, tmp_path: Path) -> None:
        """HEIC → JPG → PNG → JPG must preserve EXIF."""
        a = tmp_path / "a.jpg"
        b = tmp_path / "b.png"
        c = tmp_path / "c.jpg"
        assert main([str(_HEIC), str(a)]) == 0
        assert main([str(a), str(b)]) == 0
        assert main([str(b), str(c)]) == 0
        with Image.open(c) as img:
            exif = img.getexif()
            assert exif.get(ExifBase.Make) or exif.get(ExifBase.Model), \
                "EXIF lost in HEIC→JPG→PNG→JPG roundtrip"

    def test_icc_profile_preserved(self, tmp_path: Path) -> None:
        """If the HEIC has an ICC profile it should survive to PNG."""
        src_data = read_image(_HEIC)
        if "icc_profile" not in src_data.metadata:
            pytest.skip("source HEIC has no ICC profile")
        out = tmp_path / "icc.png"
        assert main([str(_HEIC), str(out)]) == 0
        with Image.open(out) as img:
            assert img.info.get("icc_profile"), "ICC profile lost in HEIC → PNG"


# ═══════════════════════════════════════════════════════════════════════════
#  HEIC — roundtrip quality
# ═══════════════════════════════════════════════════════════════════════════


class TestHeicRoundtrip:
    def test_heic_png_heic_dimensions(self, tmp_path: Path) -> None:
        """HEIC → PNG → HEIF roundtrip must preserve dimensions."""
        mid = tmp_path / "mid.png"
        out = tmp_path / "out.heif"
        assert main([str(_HEIC), str(mid)]) == 0
        assert main([str(mid), str(out)]) == 0
        src_data = read_image(_HEIC)
        out_data = read_image(out)
        assert src_data.frames[0].size == out_data.frames[0].size

    def test_heic_avif_png_dimensions(self, tmp_path: Path) -> None:
        """HEIC → AVIF → PNG roundtrip."""
        a = tmp_path / "a.avif"
        b = tmp_path / "b.png"
        assert main([str(_HEIC), str(a)]) == 0
        assert main([str(a), str(b)]) == 0
        src_data = read_image(_HEIC)
        with Image.open(b) as img:
            assert img.size == src_data.frames[0].size

    def test_heic_to_lossless_bmp_pixel_count(self, tmp_path: Path) -> None:
        """BMP is lossless — pixel count must match."""
        out = tmp_path / "out.bmp"
        assert main([str(_HEIC), str(out)]) == 0
        src_data = read_image(_HEIC)
        with Image.open(out) as img:
            sw, sh = src_data.frames[0].size
            assert img.size == (sw, sh)


# ═══════════════════════════════════════════════════════════════════════════
#  HEIC — chain conversions
# ═══════════════════════════════════════════════════════════════════════════


class TestHeicChain:
    def test_chain_heic_jpg_webp_tiff_png(self, tmp_path: Path) -> None:
        """HEIC → JPG → WebP → TIFF → PNG must all succeed."""
        steps = [
            ("a.jpg", None),
            ("b.webp", "a.jpg"),
            ("c.tiff", "b.webp"),
            ("d.png", "c.tiff"),
        ]
        prev = str(_HEIC)
        for name, _ in steps:
            nxt = tmp_path / name
            assert main([prev, str(nxt)]) == 0
            assert nxt.stat().st_size > 0
            prev = str(nxt)
        with Image.open(tmp_path / "d.png") as img:
            assert img.size[0] > 0

    def test_chain_heic_png_bmp_tga_ppm_png(self, tmp_path: Path) -> None:
        """All-lossless chain: HEIC → PNG → BMP → TGA → PPM → PNG."""
        chain = ["a.png", "b.bmp", "c.tga", "d.ppm", "e.png"]
        prev = str(_HEIC)
        for name in chain:
            nxt = tmp_path / name
            assert main([prev, str(nxt)]) == 0
            prev = str(nxt)
        # Lossless chain: first PNG and last PNG should be pixel-identical
        with Image.open(tmp_path / "a.png") as first, \
             Image.open(tmp_path / "e.png") as last:
            assert first.size == last.size
            assert first.convert("RGB").tobytes() == \
                   last.convert("RGB").tobytes()


# ═══════════════════════════════════════════════════════════════════════════
#  GIF source — frame handling
# ═══════════════════════════════════════════════════════════════════════════


class TestGifFrames:
    """Test multi-frame behaviour with the real GIF file."""

    def test_gif_has_frames(self) -> None:
        data = read_image(_GIF)
        assert len(data.frames) >= 1

    def test_gif_to_jpg_first_frame(self, tmp_path: Path) -> None:
        """Specific filename → first frame only."""
        out = tmp_path / "first.jpg"
        assert main([str(_GIF), str(out)]) == 0
        with Image.open(out) as img:
            assert img.format == "JPEG"
            assert getattr(img, "n_frames", 1) == 1

    def test_gif_to_png_first_frame(self, tmp_path: Path) -> None:
        out = tmp_path / "first.png"
        assert main([str(_GIF), str(out)]) == 0
        with Image.open(out) as img:
            assert img.format == "PNG"

    def test_gif_star_extracts_all_frames(self, tmp_path: Path) -> None:
        """'*.png' must produce one file per frame."""
        data = read_image(_GIF)
        n = len(data.frames)
        pattern = str(tmp_path / "frame_*.png")
        assert main([str(_GIF), pattern]) == 0
        found = sorted(tmp_path.glob("frame_*.png"))
        assert len(found) == n

    def test_gif_star_frames_are_valid(self, tmp_path: Path) -> None:
        """Each extracted frame must be a valid image with correct size."""
        data = read_image(_GIF)
        expected_size = data.frames[0].size
        pattern = str(tmp_path / "*.png")
        assert main([str(_GIF), pattern]) == 0
        for p in sorted(tmp_path.glob("*.png")):
            with Image.open(p) as img:
                assert img.size == expected_size

    def test_gif_star_to_jpg(self, tmp_path: Path) -> None:
        """Extract all frames as JPEG."""
        data = read_image(_GIF)
        n = len(data.frames)
        pattern = str(tmp_path / "*.jpg")
        assert main([str(_GIF), pattern]) == 0
        found = sorted(tmp_path.glob("*.jpg"))
        assert len(found) == n
        for p in found:
            with Image.open(p) as img:
                assert img.format == "JPEG"

    def test_gif_star_zero_padding(self, tmp_path: Path) -> None:
        """If >= 10 frames, filenames should be zero-padded."""
        data = read_image(_GIF)
        n = len(data.frames)
        pattern = str(tmp_path / "*.bmp")
        assert main([str(_GIF), pattern]) == 0
        if n >= 10:
            width = len(str(n))
            first = tmp_path / f"{'1'.zfill(width)}.bmp"
            assert first.exists(), f"expected zero-padded {first.name}"


# ═══════════════════════════════════════════════════════════════════════════
#  GIF source — conversion to various formats
# ═══════════════════════════════════════════════════════════════════════════


class TestGifToFormats:
    @pytest.mark.parametrize("ext", [
        "jpg", "png", "bmp", "tiff", "webp", "avif", "heif", "tga", "ppm",
    ])
    def test_gif_to_format(self, tmp_path: Path, ext: str) -> None:
        out = tmp_path / f"gif_out.{ext}"
        assert main([str(_GIF), str(out)]) == 0
        assert out.exists()
        assert out.stat().st_size > 0

    def test_gif_to_jpg_dimensions(self, tmp_path: Path) -> None:
        out = tmp_path / "dim.jpg"
        assert main([str(_GIF), str(out)]) == 0
        src = read_image(_GIF)
        with Image.open(out) as img:
            assert img.size == src.frames[0].size

    def test_gif_to_webp_valid(self, tmp_path: Path) -> None:
        out = tmp_path / "out.webp"
        assert main([str(_GIF), str(out)]) == 0
        with Image.open(out) as img:
            assert img.format == "WEBP"

    def test_gif_to_gif_reencode(self, tmp_path: Path) -> None:
        out = tmp_path / "reencode.gif"
        assert main([str(_GIF), str(out)]) == 0
        with Image.open(out) as img:
            assert img.format == "GIF"


# ═══════════════════════════════════════════════════════════════════════════
#  GIF — chain conversions
# ═══════════════════════════════════════════════════════════════════════════


class TestGifChain:
    def test_chain_gif_png_jpg_webp(self, tmp_path: Path) -> None:
        a = tmp_path / "a.png"
        b = tmp_path / "b.jpg"
        c = tmp_path / "c.webp"
        assert main([str(_GIF), str(a)]) == 0
        assert main([str(a), str(b)]) == 0
        assert main([str(b), str(c)]) == 0
        with Image.open(c) as img:
            assert img.format == "WEBP"

    def test_chain_gif_bmp_tiff_png_lossless(self, tmp_path: Path) -> None:
        """Lossless chain from GIF first frame."""
        a = tmp_path / "a.bmp"
        b = tmp_path / "b.tiff"
        c = tmp_path / "c.png"
        assert main([str(_GIF), str(a)]) == 0
        assert main([str(a), str(b)]) == 0
        assert main([str(b), str(c)]) == 0
        # BMP → TIFF → PNG must be pixel-identical
        with Image.open(a) as ia, Image.open(c) as ic:
            assert ia.convert("RGB").tobytes() == \
                   ic.convert("RGB").tobytes()


# ═══════════════════════════════════════════════════════════════════════════
#  Cross-source: GIF ↔ HEIC format interchange
# ═══════════════════════════════════════════════════════════════════════════


class TestCrossSource:
    def test_heic_and_gif_to_same_format(self, tmp_path: Path) -> None:
        """Both assets should convert to PNG successfully."""
        h = tmp_path / "h.png"
        g = tmp_path / "g.png"
        assert main([str(_HEIC), str(h)]) == 0
        assert main([str(_GIF), str(g)]) == 0
        with Image.open(h) as ih, Image.open(g) as ig:
            assert ih.format == "PNG"
            assert ig.format == "PNG"

    def test_gif_frame_to_heif_and_back(self, tmp_path: Path) -> None:
        """GIF (first frame) → HEIF → PNG roundtrip."""
        a = tmp_path / "a.heif"
        b = tmp_path / "b.png"
        assert main([str(_GIF), str(a)]) == 0
        assert main([str(a), str(b)]) == 0
        src = read_image(_GIF)
        with Image.open(b) as img:
            assert img.size == src.frames[0].size

    def test_heic_to_gif(self, tmp_path: Path) -> None:
        """A photo converted to GIF should still be valid."""
        out = tmp_path / "photo.gif"
        assert main([str(_HEIC), str(out)]) == 0
        with Image.open(out) as img:
            assert img.format == "GIF"


# ═══════════════════════════════════════════════════════════════════════════
#  Safe-write with real files (principle 8)
# ═══════════════════════════════════════════════════════════════════════════


class TestSafeWriteReal:
    def test_heic_source_not_modified(self, tmp_path: Path) -> None:
        original = _HEIC.read_bytes()
        out = tmp_path / "out.jpg"
        main([str(_HEIC), str(out)])
        assert _HEIC.read_bytes() == original

    def test_gif_source_not_modified(self, tmp_path: Path) -> None:
        original = _GIF.read_bytes()
        out = tmp_path / "out.png"
        main([str(_GIF), str(out)])
        assert _GIF.read_bytes() == original

    def test_no_leftover_temp_files(self, tmp_path: Path) -> None:
        """After a successful conversion no temp files should remain."""
        out = tmp_path / "clean.jpg"
        assert main([str(_HEIC), str(out)]) == 0
        # Only the output file should be in tmp_path
        files = list(tmp_path.iterdir())
        assert files == [out]
