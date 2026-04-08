"""Image format readers and writers.

All dependencies are pip-installable — no system packages required.

Tier 1 – Pillow + plugins    (most raster formats, HEIF/AVIF)
Tier 2 – rawpy               (camera RAW)
Tier 3 – psd-tools           (PSD / PSB)
Tier 4 – svglib + reportlab  (SVG rasterisation)
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms

from any2any.converters import ImageData, _readers, _writers

# ── optional dependency probes (all pip-installable) ─────────────────────

_heif_ok = False
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    _heif_ok = True
except ImportError:
    pass

_jxl_ok = False
try:
    import pillow_jxl as _pillow_jxl  # noqa: F401

    _jxl_ok = True
except ImportError:
    pass

_rawpy_ok = False
try:
    import rawpy as _rawpy_mod  # type: ignore[import-untyped]

    _rawpy_ok = True
except ImportError:
    pass

_psd_ok = False
try:
    import psd_tools as _psd_mod  # type: ignore[import-untyped]

    _psd_ok = True
except ImportError:
    pass

_svg_ok = False
try:
    from svglib.svglib import svg2rlg  # type: ignore[import-untyped]
    from reportlab.graphics import renderPM  # type: ignore[import-untyped]

    _svg_ok = True
except ImportError:
    pass

# ── format constants ─────────────────────────────────────────────────────

# Extension → Pillow format string (used for save).
_EXT_FMT: dict[str, str] = {
    "bmp": "BMP",
    "dib": "DIB",
    "gif": "GIF",
    "ico": "ICO",
    "jpeg": "JPEG",
    "jpg": "JPEG",
    "jpe": "JPEG",
    "jfif": "JPEG",
    "png": "PNG",
    "tga": "TGA",
    "tiff": "TIFF",
    "tif": "TIFF",
    "webp": "WEBP",
    "ppm": "PPM",
    "pgm": "PPM",
    "pbm": "PPM",
    "xbm": "XBM",
    "xpm": "XPM",
    "pcx": "PCX",
    "jp2": "JPEG2000",
    "j2k": "JPEG2000",
    "icns": "ICNS",
    "dds": "DDS",
    "sgi": "SGI",
    "rgb": "SGI",
    "bw": "SGI",
    "pdf": "PDF",
    "eps": "EPS",
    "cur": "CUR",
    "pict": "PICT",
    "pct": "PICT",
}
if _heif_ok:
    _EXT_FMT |= {"heic": "HEIF", "heif": "HEIF", "avif": "AVIF"}
if _jxl_ok:
    _EXT_FMT["jxl"] = "JXL"

# Pillow readable / writable subsets.
_PIL_READ: set[str] = set(_EXT_FMT.keys())
# XPM, CUR, PICT are read-only in Pillow.
_PIL_WRITE: set[str] = set(_EXT_FMT.keys()) - {"xpm", "cur", "pict", "pct"}

# Camera RAW extensions (read-only, via rawpy).
_RAW_EXTS: set[str] = {
    "raw", "cr2", "cr3", "nef", "arw", "dng",
    "orf", "rw2", "pef", "raf", "srw",
}

# ── colour-mode constraints ──────────────────────────────────────────────

_RGB_ONLY: set[str] = {"JPEG", "BMP", "PPM", "PCX", "DDS", "EPS", "PDF"}
_NO_PALETTE: set[str] = {
    "JPEG", "BMP", "TIFF", "PPM", "SGI", "DDS",
    "HEIF", "AVIF", "JPEG2000",
}

# ── metadata support per format ──────────────────────────────────────────

_EXIF_FMTS: set[str] = {"JPEG", "PNG", "WEBP", "TIFF", "HEIF", "AVIF", "JXL", "JPEG2000"}
_ICC_FMTS: set[str] = {"JPEG", "PNG", "WEBP", "TIFF", "HEIF", "AVIF", "JXL", "JPEG2000"}
_XMP_FMTS: set[str] = {"PNG", "WEBP", "TIFF", "JPEG", "JXL"}

# ── max-quality / lossless save kwargs ───────────────────────────────────

_QUALITY: dict[str, dict[str, object]] = {
    "JPEG": {"quality": 100, "subsampling": 0},
    "WEBP": {"quality": 100, "method": 6},
    "HEIF": {"quality": 100},
    "AVIF": {"quality": 100},
    "JXL": {"quality": 100},
    "JPEG2000": {"irreversible": False},
    "TIFF": {"compression": "tiff_lzw"},
    "PNG": {"compress_level": 9},
}

_SRGB = ImageCms.createProfile("sRGB")

# ── metadata helpers ─────────────────────────────────────────────────────


def _extract_meta(img: Image.Image) -> dict[str, object]:
    meta: dict[str, object] = {}
    exif_bytes = img.info.get("exif")
    if isinstance(exif_bytes, bytes) and exif_bytes:
        meta["exif"] = exif_bytes
    else:
        exif_obj = img.getexif()
        if exif_obj:
            raw = exif_obj.tobytes()
            if raw:
                meta["exif"] = raw
    xmp = img.info.get("xmp")
    if isinstance(xmp, bytes) and xmp:
        meta["xmp"] = xmp
    icc = img.info.get("icc_profile")
    if isinstance(icc, bytes) and icc:
        meta["icc_profile"] = icc
    dpi = img.info.get("dpi")
    if dpi:
        meta["dpi"] = dpi
    return meta


def _save_kwargs(meta: dict[str, object], fmt: str) -> dict[str, object]:
    kw: dict[str, object] = {"format": fmt}
    if fmt in _QUALITY:
        kw.update(_QUALITY[fmt])
    if fmt in _EXIF_FMTS and "exif" in meta:
        kw["exif"] = meta["exif"]
    if fmt in _XMP_FMTS and "xmp" in meta:
        kw["xmp"] = meta["xmp"]
    if fmt in _ICC_FMTS and "icc_profile" in meta:
        kw["icc_profile"] = meta["icc_profile"]
    if "dpi" in meta:
        kw["dpi"] = meta["dpi"]
    return kw


# ── colour-space / mode conversion ──────────────────────────────────────


def _cms_to_srgb(img: Image.Image, meta: dict[str, object]) -> Image.Image:
    """CMYK → sRGB via ICC profile (principle 5)."""
    if img.mode != "CMYK":
        return img
    icc_data = meta.get("icc_profile")
    if isinstance(icc_data, bytes):
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc_data))
            dst = ImageCms.ImageCmsProfile(_SRGB)
            img = ImageCms.profileToProfile(img, src, dst, outputMode="RGB")
            buf = io.BytesIO()
            ImageCms.ImageCmsProfile(_SRGB).save(buf)
            meta["icc_profile"] = buf.getvalue()
            return img
        except Exception:
            pass
    return img.convert("RGB")


def _hi_to_8bit(img: Image.Image) -> Image.Image:
    """16-bit / float → 8-bit with proper mapping (principle 2)."""
    if img.mode in ("I", "I;16", "I;16L", "I;16B", "I;16N"):
        arr = np.array(img, dtype=np.float64)
        mx = arr.max()
        if mx > 0:
            arr = (arr / mx * 255).clip(0, 255)
        return Image.fromarray(arr.astype(np.uint8), mode="L")
    if img.mode == "F":
        arr = np.array(img, dtype=np.float64)
        mx = arr.max()
        if mx > 0:
            arr = (arr / mx * 255).clip(0, 255)
        return Image.fromarray(arr.astype(np.uint8), mode="L")
    return img


def _ensure_mode(
    img: Image.Image, fmt: str, meta: dict[str, object],
) -> Image.Image:
    img = _cms_to_srgb(img, meta)
    img = _hi_to_8bit(img)
    if fmt in _RGB_ONLY:
        if img.mode not in ("RGB", "L", "1"):
            img = img.convert("RGB")
    elif fmt in _NO_PALETTE and img.mode == "P":
        img = img.convert("RGBA" if "transparency" in img.info else "RGB")
    return img


# ── readers ──────────────────────────────────────────────────────────────


def _read_pillow(path: Path) -> ImageData:
    """Read any format Pillow (+ plugins) can open."""
    img = Image.open(path)
    meta = _extract_meta(img)
    frames: list[Image.Image] = []
    n = getattr(img, "n_frames", 1)
    for i in range(n):
        img.seek(i)
        frames.append(img.copy())
    img.close()
    return ImageData(frames=frames, metadata=meta)


def _read_raw(path: Path) -> ImageData:
    """Read camera RAW via rawpy (pip wheels bundle libraw)."""
    if not _rawpy_ok:
        raise ImportError("rawpy is required for RAW support: pip install rawpy")
    with _rawpy_mod.imread(str(path)) as raw:
        rgb16 = raw.postprocess(use_camera_wb=True, output_bps=16)
    rgb8 = (rgb16.astype(np.float64) / 65535 * 255).clip(0, 255).astype(np.uint8)
    img = Image.fromarray(rgb8, mode="RGB")
    # Try pulling EXIF from the embedded JPEG preview.
    meta: dict[str, object] = {}
    try:
        with Image.open(path) as preview:
            meta = _extract_meta(preview)
    except Exception:
        pass
    return ImageData(frames=[img], metadata=meta)


def _read_psd(path: Path) -> ImageData:
    """Read PSD/PSB via psd-tools, merging all layers (principle 3)."""
    if not _psd_ok:
        raise ImportError("psd-tools is required for PSD support: pip install psd-tools")
    psd = _psd_mod.PSDImage.open(path)
    img = psd.composite()
    meta: dict[str, object] = {}
    try:
        icc = getattr(psd, "icc_profile", None)
        if icc:
            meta["icc_profile"] = bytes(icc)
    except Exception:
        pass
    return ImageData(frames=[img], metadata=meta)


def _read_svg(path: Path) -> ImageData:
    """Rasterise SVG via svglib + reportlab (principle 6: 96 DPI)."""
    if not _svg_ok:
        raise ImportError(
            "svglib and reportlab are required for SVG support: "
            "pip install svglib reportlab"
        )
    drawing = svg2rlg(str(path))
    if drawing is None:
        raise ValueError(f"svglib could not parse {path}")
    buf = io.BytesIO()
    renderPM.drawToFile(drawing, buf, fmt="PNG", dpi=96)
    buf.seek(0)
    img = Image.open(buf).copy()
    return ImageData(frames=[img], metadata={"dpi": (96, 96)})


# ── writers ──────────────────────────────────────────────────────────────


def _write_pillow(data: ImageData, path: Path) -> None:
    """Write via Pillow (+ plugins).  Max quality, preserve metadata."""
    ext = path.suffix.lower().lstrip(".")
    fmt = _EXT_FMT[ext]
    frame = data.frames[0]
    meta = dict(data.metadata)
    frame = _ensure_mode(frame, fmt, meta)
    kw = _save_kwargs(meta, fmt)
    frame.save(path, **kw)


# ── registration ─────────────────────────────────────────────────────────

# Pillow-readable (including HEIF/AVIF/JXL when plugins loaded).
for _e in _PIL_READ:
    _readers[_e] = _read_pillow

# Camera RAW (rawpy).
for _e in _RAW_EXTS:
    _readers[_e] = _read_raw

# PSD / PSB.
_readers["psd"] = _read_psd
_readers["psb"] = _read_psd

# SVG (svglib + reportlab).
_readers["svg"] = _read_svg

# Pillow-writable.
for _e in _PIL_WRITE:
    _writers[_e] = _write_pillow
