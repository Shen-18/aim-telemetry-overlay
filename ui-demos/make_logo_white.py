"""把白底蓝色 SCUT Racing logo 转成纯白透明 PNG。

以像素到白色背景的最大通道距离恢复 alpha，而不用蓝红通道差。
这样抗锯齿或压缩后偏灰的蓝色笔画也不会被误判为透明裂纹。

两处容易踩的坑（都会让成品「发虚」）：
1. 全局参考值冲淡细笔画：`Racing` 的下划线、大字里的小笔画本来就窄，
   压缩/重采样后峰值低于整体实心值，按全局参考值换算就永远到不了 255，
   在深色背景上显示成半透明灰线。→ 用「内部实心化」修正（见 solidify_interior）。
2. 压缩雾点：笔画周围一圈极低覆盖率的像素，放大看是脏边。→ 用 haze 阈值清掉。

用法：python make_logo_white.py [输入] [输出]
默认：Data/logo.png → assets/logo_white.png（相对本脚本）
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

HERE = Path(__file__).resolve().parent
DEFAULT_SRC = Path(r"D:\Desktop\SCUTRacingTelemetry\Data\logo.png")
DEFAULT_DST = HERE / "assets" / "logo_white.png"

# 到此距离以内视为背景（纯白区域的采样噪声）
BACKGROUND_MAX = 24.0
# 压缩雾点上限：清成全透明，避免放大后看到脏边
HAZE_MAX = 40.0
# 内部实心化的保护带宽度（像素）：贴着背景这个距离内保留抗锯齿过渡
EDGE_BAND = 2


def extract_alpha(rgb: np.ndarray) -> np.ndarray:
    """从白底彩色图中恢复前景覆盖率，输出 0..255。"""
    distance = 255.0 - np.min(rgb, axis=2)
    foreground = distance[distance > BACKGROUND_MAX]
    if foreground.size == 0:
        raise ValueError("No logo pixels found")
    solid = max(float(np.percentile(foreground, 75)), 160.0)
    alpha = np.clip((distance - BACKGROUND_MAX) / (solid - BACKGROUND_MAX), 0.0, 1.0) * 255.0
    alpha[distance <= HAZE_MAX] = 0.0
    return solidify_interior(alpha, distance)


def solidify_interior(alpha: np.ndarray, distance: np.ndarray) -> np.ndarray:
    """距背景 EDGE_BAND 像素以外一律按实心处理，抗锯齿只留在贴边的一条带上。

    细笔画的峰值低于全局 solid 值，不修正就会整条发虚；而笔画内部的深浅不匀
    （压缩残留）也一并抹平，放大看不会再有灰斑。
    """
    background = (distance <= HAZE_MAX).astype(np.uint8) * 255
    near_background = np.asarray(
        Image.fromarray(background).filter(ImageFilter.MaxFilter(EDGE_BAND * 2 + 1))
    ) > 0
    return np.where(near_background, alpha, 255.0)


def convert(src: Path, dst: Path) -> Image.Image:
    im = Image.open(src).convert("RGBA")
    a = np.asarray(im).astype(np.float64)
    rgb = a[..., :3]

    alpha = extract_alpha(rgb)

    # 墨色不是纯黑时，中间调会略有色偏；白标不需要保留墨色，直接全白。
    out = np.zeros_like(a)
    out[..., :3] = 255.0
    out[..., 3] = alpha

    result = Image.fromarray(out.astype(np.uint8), "RGBA")
    bbox = result.getbbox()
    if bbox:
        result = result.crop(bbox)
    dst.parent.mkdir(parents=True, exist_ok=True)
    result.save(dst)
    print(f"white-distance alpha -> {dst}  size={result.size}")
    return result


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_DST
    convert(src, dst)
