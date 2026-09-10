from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from vl_convert import svg_to_png


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "frontend" / "public" / "favicon.svg"
OUTPUT = Path(__file__).with_name("OpenSportsAnalyst.ico")


def main() -> None:
    png = svg_to_png(SOURCE.read_text(encoding="utf-8"), scale=2)
    with Image.open(io.BytesIO(png)) as image:
        image.convert("RGBA").save(
            OUTPUT,
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
    print(f"Generated {OUTPUT}")


if __name__ == "__main__":
    main()
