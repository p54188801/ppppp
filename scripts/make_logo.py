"""生成应用图标（晨光太阳 + 书本）并输出 PNG/ICO。"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(r"D:\EduFlow\assets")
OUT.mkdir(parents=True, exist_ok=True)


def make(size: int = 512) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 圆角底：晨光渐变（橙 -> 黄 -> 天蓝）
    radius = int(size * 0.24)
    bg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bg)
    top, bottom = (255, 176, 64), (62, 168, 255)
    for y in range(size):
        t = y / max(1, size - 1)
        color = (
            int(top[0] + (bottom[0] - top[0]) * t),
            int(top[1] + (bottom[1] - top[1]) * t),
            int(top[2] + (bottom[2] - top[2]) * t),
            255,
        )
        bd.line([(0, y), (size, y)], fill=color)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    img.paste(bg, (0, 0), mask)

    # 太阳
    cx, cy, r = int(size * 0.5), int(size * 0.42), int(size * 0.17)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 246, 214, 255))
    d.ellipse([cx - r + 6, cy - r + 6, cx + r - 6, cy + r - 6], fill=(255, 214, 102, 255))

    # 光芒
    import math

    for i in range(12):
        ang = math.radians(i * 30)
        x1 = cx + math.cos(ang) * (r + 10)
        y1 = cy + math.sin(ang) * (r + 10)
        x2 = cx + math.cos(ang) * (r + 26)
        y2 = cy + math.sin(ang) * (r + 26)
        d.line([(x1, y1), (x2, y2)], fill=(255, 236, 170, 230), width=max(3, size // 90))

    # 书本
    bw, bh = int(size * 0.46), int(size * 0.26)
    bx, by = (size - bw) // 2, int(size * 0.62)
    d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=int(size * 0.03), fill=(255, 255, 255, 245))
    mid = bx + bw // 2
    d.line([(mid, by + 6), (mid, by + bh - 6)], fill=(198, 217, 238, 255), width=max(2, size // 160))
    for i in range(3):
        yy = by + int(bh * 0.28) + i * int(bh * 0.2)
        d.line([(bx + bw * 0.12, yy), (mid - bw * 0.08, yy)], fill=(160, 190, 220, 255), width=max(2, size // 200))
        d.line([(mid + bw * 0.08, yy), (bx + bw * 0.88, yy)], fill=(160, 190, 220, 255), width=max(2, size // 200))

    return img


icon = make(512)
icon.save(OUT / "logo.png")
icon.resize((256, 256), Image.LANCZOS).save(
    OUT / "logo.ico",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
print("已生成:", OUT / "logo.png", OUT / "logo.ico")
