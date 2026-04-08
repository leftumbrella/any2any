# any2any 构建与运行指南

## 环境要求

- Python >= 3.10
- pip

**无需安装任何系统级依赖**，所有依赖均通过 pip 安装。

## 安装步骤

### 1. 克隆仓库

```bash
git clone <仓库地址>
cd any2any
```

### 2. 创建虚拟环境（推荐）

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# 或
.venv\Scripts\activate     # Windows
```

### 3. 安装项目

```bash
pip install -e .
```

如需 SVG 支持：

```bash
pip install -e ".[svg]"
```

如需 JPEG XL 支持：

```bash
pip install -e ".[jxl]"
```

安装所有可选格式 + 开发依赖：

```bash
pip install -e ".[all,dev]"
```

## 使用方法

```bash
any2any 输入文件 输出文件
```

程序根据扩展名自动识别格式并转换。

### 示例

```bash
# 基本格式转换
any2any photo.png photo.jpg
any2any image.jpg image.webp

# HEIC/AVIF（iPhone 照片）
any2any photo.heic photo.png
any2any image.png image.avif

# RAW 相机文件
any2any DSC_0001.nef output.jpg
any2any IMG_0001.cr3 output.png

# PSD 图层合并导出
any2any design.psd design.png

# SVG 矢量转光栅（需安装 svg 可选依赖）
any2any icon.svg icon.png

# 动画 GIF 提取全部帧
any2any animated.gif "*.png"
# 输出：1.png, 2.png, 3.png, ...

# 动画 GIF 仅保留第一帧
any2any animated.gif first_frame.jpg
```

### 转换原则

- **最高质量**：有损格式（JPEG、WebP、HEIF、AVIF）使用最高质量输出
- **EXIF 完整保留**：拍摄时间、地点、相机参数、XMP、ICC 色彩配置文件全部拷贝
- **色彩空间映射**：CMYK → sRGB 通过 ICC Profile 精确转换，不丢弃色彩信息
- **高色深映射**：16-bit / HDR 向 8-bit 转换时做归一化映射
- **图层合并**：PSD 等多图层格式转换时合并所有可见图层
- **矢量 96 DPI**：SVG 转光栅时默认 96 DPI
- **动画帧控制**：指定文件名保留第一帧，`*.ext` 通配符提取全部帧
- **安全写入**：通过临时文件写入，转换失败时源文件不受影响

### 支持的格式

| 分类 | 格式 | 扩展名 | 读 | 写 |
|------|------|--------|:--:|:--:|
| 通用光栅 | BMP | .bmp, .dib | ✓ | ✓ |
| | GIF | .gif | ✓ | ✓ |
| | ICO | .ico | ✓ | ✓ |
| | JPEG | .jpg, .jpeg, .jpe, .jfif | ✓ | ✓ |
| | PNG | .png | ✓ | ✓ |
| | TGA | .tga | ✓ | ✓ |
| | TIFF | .tif, .tiff | ✓ | ✓ |
| | WebP | .webp | ✓ | ✓ |
| 现代格式 | AVIF | .avif | ✓ | ✓ |
| | HEIC/HEIF | .heic, .heif | ✓ | ✓ |
| | JPEG XL | .jxl | ✓° | ✓° |
| | JPEG 2000 | .jp2, .j2k | ✓ | ✓ |
| RAW 相机 | Canon | .cr2, .cr3 | ✓ | — |
| | Nikon | .nef | ✓ | — |
| | Sony | .arw | ✓ | — |
| | Adobe DNG | .dng | ✓ | — |
| | Olympus | .orf | ✓ | — |
| | Panasonic | .rw2 | ✓ | — |
| | Pentax | .pef | ✓ | — |
| | Fujifilm | .raf | ✓ | — |
| | Samsung | .srw | ✓ | — |
| | 通用 RAW | .raw | ✓ | — |
| 设计工具 | PSD | .psd | ✓ | — |
| | PSB | .psb | ✓ | — |
| 矢量 | SVG | .svg | ✓° | — |
| | EPS | .eps | ✓ | ✓ |
| 文档 | PDF | .pdf | ✓ | ✓ |
| 其他光栅 | PPM/PGM/PBM | .ppm, .pgm, .pbm | ✓ | ✓ |
| | XBM | .xbm | ✓ | ✓ |
| | XPM | .xpm | ✓ | — |
| | PCX | .pcx | ✓ | ✓ |
| | DDS | .dds | ✓ | ✓ |
| | SGI | .sgi, .rgb, .bw | ✓ | ✓ |
| | ICNS | .icns | ✓ | ✓ |
| | CUR | .cur | ✓ | — |
| | PICT | .pict, .pct | ✓ | — |

- ✓ = 核心支持（pip install 即可）
- ✓° = 需安装可选依赖（`pip install any2any[svg]` 或 `pip install any2any[jxl]`）
- — = 格式本身为只读

## 运行测试

```bash
pytest
```

带覆盖率报告：

```bash
pytest --cov=any2any
```

## 查看版本

```bash
any2any --version
```
