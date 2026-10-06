"""Resize the approved XinYu artwork into checked-in platform icon resources.

Requires Pillow (development only). The source artwork is never modified.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
CLIENT = ROOT / "clients" / "xinyu_flutter"
SOURCE = ROOT / "assets" / "branding" / "xinyu-logo.png"
DENSITIES = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}


def save_png(artwork: Image.Image, path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    artwork.resize((size, size), Image.Resampling.LANCZOS).save(path, optimize=True)


def main() -> None:
    with Image.open(SOURCE) as original:
        if original.width != original.height:
            raise ValueError("The approved artwork must be square; do not crop it automatically.")
        artwork = original.convert("RGBA")

    save_png(artwork, CLIENT / "assets/branding/xinyu-logo.png", 256)
    web = ROOT / "companion_agent/web/branding"
    save_png(artwork, web / "xinyu-logo.png", 256)
    save_png(artwork, web / "favicon-32.png", 32)
    save_png(artwork, web / "apple-touch-icon.png", 180)
    artwork.save(web / "favicon.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64)])

    artwork.save(
        CLIENT / "windows/runner/resources/app_icon.ico",
        sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)],
    )
    resources = CLIENT / "android/app/src/main/res"
    for density, scale in DENSITIES.items():
        save_png(artwork, resources / f"mipmap-{density}/ic_launcher.png", round(48 * scale))
        # Android adaptive layers use 108 dp; keep the supplied artwork in the
        # central 72 dp, including its white margin, so its mark fits the safe area.
        canvas_size = round(108 * scale)
        content_size = round(72 * scale)
        foreground = Image.new("RGBA", (canvas_size, canvas_size))
        content = artwork.resize((content_size, content_size), Image.Resampling.LANCZOS)
        inset = (canvas_size - content_size) // 2
        foreground.alpha_composite(content, (inset, inset))
        destination = resources / f"drawable-{density}/ic_launcher_foreground.png"
        destination.parent.mkdir(parents=True, exist_ok=True)
        foreground.save(destination, optimize=True)

    print("Prepared Flutter, web, Windows and Android logo resources from the approved PNG.")


if __name__ == "__main__":
    main()
