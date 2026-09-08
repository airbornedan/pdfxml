"""Raster image helpers for converting samples into monochrome line art."""

from pathlib import Path

import cv2


def edge_detect_line_art(source_path, destination_path=None, *, lower_threshold=50, upper_threshold=150):
    """Return monochrome edge-detected PNG bytes for an input raster image.

    The image is loaded from source_path, converted to grayscale, denoised,
    and then processed with Canny edge detection. The result is saved as a
    black-and-white PNG if destination_path is supplied.
    """
    src = Path(source_path)
    image = cv2.imread(str(src), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(f"Could not read image: {source_path}")

    denoised = cv2.medianBlur(image, 5)
    edges = cv2.Canny(denoised, lower_threshold, upper_threshold)

    # Canny already produces a monochrome edge map; keep the output as a
    # binary image so the result is easy to use in downstream tooling.
    _, binary = cv2.threshold(edges, 0, 255, cv2.THRESH_BINARY)

    success, buffer = cv2.imencode(".png", binary)
    if not success:
        raise RuntimeError(f"Could not encode {source_path} as PNG")

    png_bytes = buffer.tobytes()
    if destination_path is not None:
        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(png_bytes)

    return png_bytes
