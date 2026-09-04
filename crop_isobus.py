"""Crop the fixed ISOBUS VT region from agricultural display screenshots."""
import argparse
from pathlib import Path

import fitz


# Bounds measured from tests/sample.png. The right and bottom values are
# exclusive, as required by PyMuPDF's clip rectangle.
ISOBUS_RECT = fitz.Rect(371, 4, 1549, 1076)


def crop_isobus(source: str | Path, destination: str | Path) -> None:
    """Crop one display screenshot and save the ISOBUS panel as a PNG."""
    source_path = Path(source)
    destination_path = Path(destination)
    document = fitz.open(str(source_path))
    page = document[0]
    source_image = fitz.Pixmap(str(source_path))
    if source_image.width < ISOBUS_RECT.x1 or source_image.height < ISOBUS_RECT.y1:
        raise ValueError(
            f"{source_path} is {source_image.width}x{source_image.height}; expected at least "
            f"{int(ISOBUS_RECT.x1)}x{int(ISOBUS_RECT.y1)}"
        )
    scale_x = source_image.width / page.rect.width
    scale_y = source_image.height / page.rect.height
    clip = fitz.Rect(
        ISOBUS_RECT.x0 / scale_x,
        ISOBUS_RECT.y0 / scale_y,
        ISOBUS_RECT.x1 / scale_x,
        ISOBUS_RECT.y1 / scale_y,
    )
    cropped = page.get_pixmap(
        matrix=fitz.Matrix(scale_x, scale_y), clip=clip, alpha=False
    )
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(str(destination_path))
    document.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crop the fixed ISOBUS VT panel from a screenshot."
    )
    parser.add_argument("source", type=Path, help="Input screenshot")
    parser.add_argument("destination", type=Path, help="Output PNG")
    args = parser.parse_args()
    crop_isobus(args.source, args.destination)


if __name__ == "__main__":
    main()