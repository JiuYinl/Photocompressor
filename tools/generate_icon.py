from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT / "assets"
PNG_PATH = ASSETS_DIR / "app_icon.png"
ICO_PATH = ASSETS_DIR / "app_icon.ico"
ICON_SIZE = 1024


def create_gradient_background(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size))
    pixels = image.load()

    start = (13, 148, 136)
    end = (37, 99, 235)
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * (size - 1))
            r = round(start[0] * (1 - t) + end[0] * t)
            g = round(start[1] * (1 - t) + end[1] * t)
            b = round(start[2] * (1 - t) + end[2] * t)
            pixels[x, y] = (r, g, b, 255)
    return image


def rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def draw_shadow(base: Image.Image, bbox: tuple[int, int, int, int], radius: int) -> None:
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(bbox, radius=radius, fill=(4, 22, 34, 110))
    shadow = shadow.filter(ImageFilter.GaussianBlur(28))
    base.alpha_composite(shadow)


def draw_photo_card(base: Image.Image) -> None:
    size = base.size[0]
    card_bbox = (236, 250, 788, 774)
    card_radius = 88
    draw_shadow(base, (250, 270, 802, 794), card_radius)

    card = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    draw.rounded_rectangle(card_bbox, radius=card_radius, fill=(249, 250, 251, 255))
    draw.rounded_rectangle(card_bbox, radius=card_radius, outline=(255, 255, 255, 180), width=8)

    inner_bbox = (290, 314, 734, 710)
    draw.rounded_rectangle(inner_bbox, radius=58, fill=(226, 232, 240, 255))
    draw.rounded_rectangle((290, 314, 734, 500), radius=58, fill=(125, 211, 252, 255))
    draw.ellipse((618, 360, 690, 432), fill=(254, 240, 138, 255))
    draw.polygon([(320, 650), (470, 470), (585, 620)], fill=(16, 185, 129, 255))
    draw.polygon([(455, 670), (585, 440), (722, 670)], fill=(5, 150, 105, 255))
    draw.rounded_rectangle((370, 545, 440, 640), radius=18, fill=(255, 255, 255, 170))

    base.alpha_composite(card)


def inward_arrow(draw: ImageDraw.ImageDraw, points: list[tuple[int, int]], color: tuple[int, int, int, int]) -> None:
    draw.line(points[:2], fill=color, width=34)
    draw.line(points[1:3], fill=color, width=34)
    tip = points[2]
    prev = points[1]
    dx = tip[0] - prev[0]
    dy = tip[1] - prev[1]
    if dx > 0:
        arrow = [(tip[0], tip[1]), (tip[0] - 48, tip[1] - 26), (tip[0] - 48, tip[1] + 26)]
    elif dx < 0:
        arrow = [(tip[0], tip[1]), (tip[0] + 48, tip[1] - 26), (tip[0] + 48, tip[1] + 26)]
    elif dy > 0:
        arrow = [(tip[0], tip[1]), (tip[0] - 26, tip[1] - 48), (tip[0] + 26, tip[1] - 48)]
    else:
        arrow = [(tip[0], tip[1]), (tip[0] - 26, tip[1] + 48), (tip[0] + 26, tip[1] + 48)]
    draw.polygon(arrow, fill=color)


def draw_compression_marks(base: Image.Image) -> None:
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    color = (255, 255, 255, 248)

    inward_arrow(draw, [(188, 278), (188, 200), (282, 200)], color)
    inward_arrow(draw, [(836, 278), (836, 200), (742, 200)], color)
    inward_arrow(draw, [(188, 746), (188, 824), (282, 824)], color)
    inward_arrow(draw, [(836, 746), (836, 824), (742, 824)], color)

    draw.rounded_rectangle((160, 160, 864, 864), radius=220, outline=(255, 255, 255, 55), width=12)
    base.alpha_composite(overlay)


def add_gloss(base: Image.Image) -> None:
    gloss = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(gloss)
    draw.ellipse((-40, -80, 740, 420), fill=(255, 255, 255, 58))
    gloss = gloss.filter(ImageFilter.GaussianBlur(22))
    base.alpha_composite(gloss)


def build_icon() -> Image.Image:
    background = create_gradient_background(ICON_SIZE)
    mask = rounded_mask(ICON_SIZE, 220)
    background.putalpha(mask)

    vignette = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    vignette_draw = ImageDraw.Draw(vignette)
    vignette_draw.rounded_rectangle(
        (16, 16, ICON_SIZE - 17, ICON_SIZE - 17),
        radius=220,
        outline=(255, 255, 255, 42),
        width=10,
    )
    background.alpha_composite(vignette)

    add_gloss(background)
    draw_photo_card(background)
    draw_compression_marks(background)

    alpha = rounded_mask(ICON_SIZE, 220)
    background.putalpha(ImageChops.multiply(background.getchannel("A"), alpha))
    return background


def main() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    icon = build_icon()
    icon.save(PNG_PATH)
    icon.save(ICO_PATH, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(PNG_PATH)
    print(ICO_PATH)


if __name__ == "__main__":
    main()
