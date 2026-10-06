# OCR models

Text-recognition models used by `app/ocr.py` to read tables that are only a
picture. Vendored so the server never downloads anything at runtime.

| File | Source | SHA-256 |
|---|---|---|
| `en_PP-OCRv4_rec_mobile.onnx` | RapidOCR v3.9.2 (`onnx/PP-OCRv4/rec/`) | `e8770c967605983d1570cdf5352041dfb68fa0c21664f49f47b155abd3e0e318` |
| `PP-OCRv6_rec_small.onnx` | RapidOCR v3.9.2 (`onnx/PP-OCRv6/rec/`) | `6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884` |

Both are PaddleOCR models (Apache-2.0) converted to ONNX by the RapidOCR
project. Two different models are used on purpose: each cell is read by
both, and a disagreement flags the cell for a person to check.
