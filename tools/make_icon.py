"""Generate the ShiftPay app icon (run once; produces icon.ico)."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "icon.ico"
S = 1024                      # draw big, downsample for crisp edges
BG1, BG2 = (31, 36, 54), (18, 21, 32)
GREEN, AMBER, BLUE = (61, 220, 145), (255, 199, 102), (108, 159, 255)
WHITE = (244, 245, 250)


def rounded(size, radius, fill):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle([0, 0, size - 1, size - 1], radius, fill=fill)
    return img


def build():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # vertical gradient body
    grad = Image.new("RGBA", (1, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / S
        gd.point((0, y), tuple(int(BG1[i] + (BG2[i] - BG1[i]) * t) for i in range(3)) + (255,))
    grad = grad.resize((S, S))
    img.paste(grad, (0, 0), rounded(S, int(S * 0.22), (255, 255, 255, 255)))

    # calendar header bar
    d.rounded_rectangle([S * 0.17, S * 0.20, S * 0.83, S * 0.33], int(S * 0.045), fill=BLUE)
    # two hanging rings
    for cx in (0.34, 0.66):
        d.rounded_rectangle([S * cx - S * 0.028, S * 0.13, S * cx + S * 0.028, S * 0.24],
                            int(S * 0.028), fill=WHITE)

    # three day tiles: worked, sick, worked — the app's own colour language
    top, h, gap = S * 0.40, S * 0.145, S * 0.035
    left, right = S * 0.17, S * 0.83
    tile_w = (right - left - gap * 2) / 3
    for i, col in enumerate((GREEN, AMBER, GREEN)):
        x = left + i * (tile_w + gap)
        d.rounded_rectangle([x, top, x + tile_w, top + h], int(S * 0.035), fill=col)

    # pound sign on the lower band
    try:
        font = ImageFont.truetype("segoeuib.ttf", int(S * 0.30))
    except OSError:
        font = ImageFont.load_default()
    d.text((S * 0.5, S * 0.735), "£", font=font, fill=WHITE, anchor="mm")

    sizes = [256, 128, 64, 48, 32, 24, 16]
    frames = [img.resize((s, s), Image.LANCZOS) for s in sizes]
    frames[0].save(OUT, format="ICO", sizes=[(s, s) for s in sizes])
    print(f"wrote {OUT}")
    img.resize((256, 256), Image.LANCZOS).save(OUT.with_suffix(".png"))


if __name__ == "__main__":
    build()
