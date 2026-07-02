"""יוצר אייקון (.ico) פשוט ומקצועי לאפליקציה - זכוכית מגדלת על רקע כחול."""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent / "app.ico"


def make(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size

    # רקע מעוגל בגרדיאנט כחול (מדומה בשתי שכבות)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=(47, 109, 246, 255))
    d.rounded_rectangle([0, 0, s - 1, int(s * 0.6)], radius=int(s * 0.22), fill=(91, 141, 255, 255))
    d.rounded_rectangle(
        [int(s * 0.04), int(s * 0.5), s - 1, s - 1], radius=int(s * 0.18), fill=(47, 109, 246, 255)
    )

    # זכוכית מגדלת
    cx, cy, r = int(s * 0.42), int(s * 0.40), int(s * 0.20)
    lw = max(2, int(s * 0.06))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, 255), width=lw)
    # ידית
    hx1, hy1 = int(cx + r * 0.7), int(cy + r * 0.7)
    hx2, hy2 = int(s * 0.78), int(s * 0.78)
    d.line([hx1, hy1, hx2, hy2], fill=(255, 255, 255, 255), width=int(lw * 1.4))
    return img


sizes = [16, 24, 32, 48, 64, 128, 256]
imgs = [make(s) for s in sizes]
imgs[0].save(OUT, format="ICO", sizes=[(s, s) for s in sizes], append_images=imgs[1:])
print("icon saved:", OUT)
