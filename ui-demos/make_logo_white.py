"""把白底蓝色 SCUT Racing logo 转成纯白透明 PNG。

以像素到白色背景的最大通道距离恢复 alpha，而不用蓝红通道差。
这样抗锯齿或压缩后偏灰的蓝色笔画也不会被误判为透明裂纹。

用法：python make_logo_white.py [输入] [输出]
默认：Data/logo.png → assets/logo_white.png（相对本脚本）
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
DEFAULT_SRC = Path(r"D:\Desktop\SCUTRacingTelemetry\Data\logo.png")
DEFAULT_DST = HERE / "assets" / "logo_white.png"


def extract_alpha(rgb: np.ndarray) -> np.ndarray:
    """从白底彩色图中恢复前景覆盖率，输出 0..255。"""
    distance = 255.0 - np.min(rgb, axis=2)
    # PNG 来源在纯白区域仍有轻微压缩/采样噪声；先清掉它，
    # 但保留偏灰的抗锯齿笔画（它们与白色的距离远大于此）。
    noise_floor = 24.0
    foreground = distance[distance > 24.0]
    if foreground.size == 0:
        raise ValueError("No logo pixels found")
    solid = max(float(np.percentile(foreground, 75)), 160.0)
    return np.clip((distance - noise_floor) / (solid - noise_floor), 0.0, 1.0) * 255.0


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
