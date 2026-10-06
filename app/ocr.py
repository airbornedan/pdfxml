########################################################################
### OCR -- read a bordered table that's only a picture (no text layer).
### Ruling lines give the columns; they're erased so glyphs that touch
### them get clean whitespace; rows come from the ink left behind. Each
### cell is recognized by two different models -- disagreement, low
### confidence, or a cell that breaks its column's pattern is flagged
### for a human to check against the picture. CPU only, no network: the
### .onnx models ship in models/ocr/.
###
### Runs in the request process on plain pixels (the PDF itself was
### parsed in the sandbox) so the models load once and stay warm; the
### lock keeps concurrent requests from fighting over the CPU.
########################################################################
import base64
import difflib
import re
import threading
from collections import Counter

import cv2
import numpy as np

from app.extensions import OCR_KNOWN_HEADERS, OCR_MODEL_DIR, OCR_PERIOD_TO_COMMA

SCALE = 3          # upscale before everything -- source tables are often ~100 dpi
PAD = 20           # artificial whitespace around each cell crop (px, after SCALE)
CONF_MIN = 0.90    # below this (from either model) a cell is flagged
MODEL_FILES = ("en_PP-OCRv4_rec_mobile.onnx", "PP-OCRv6_rec_small.onnx")

_lock = threading.Lock()
_recognizers = None


def _load_recognizers():
    global _recognizers
    if _recognizers is None:
        from rapidocr.ch_ppocr_rec import TextRecognizer
        from rapidocr.main import DEFAULT_CFG_PATH
        from rapidocr.utils.log import logger as rapid_logger
        from rapidocr.utils.parse_parameters import ParseParams

        rapid_logger.setLevel("WARNING")
        recs = []
        for name in MODEL_FILES:
            cfg = ParseParams.load(DEFAULT_CFG_PATH)
            rec = cfg.Rec
            rec.model_path = str(OCR_MODEL_DIR / name)
            rec.model_root_dir = str(OCR_MODEL_DIR)
            rec.engine_cfg = cfg.EngineConfig[rec.engine_type.value]
            rec.font_path = None
            recs.append(TextRecognizer(rec))
        _recognizers = recs
    return _recognizers


def read_table(png_bytes):
    """PNG of the region -> {"header", "body", "flags", "fixed", "grid"}.
    flags maps "r,c" (body-relative row) to {"why", "alt", "crop"}."""
    gray = cv2.imdecode(np.frombuffer(png_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise ValueError("region image could not be decoded")
    scaled, clean, cells, grid = _segment(gray)
    if not cells:
        return {"header": None, "body": [[""]], "flags": {}, "fixed": [], "grid": grid}

    crops = [_padded(clean[b[0]:b[1], b[2]:b[3]]) if b else None for row in cells for b in row]
    with _lock:
        recs = _load_recognizers()
        reads = [_recognize(rec, crops) for rec in recs]

    rows, i = [], 0
    for row in cells:
        out = []
        for box in row:
            (ta, ca), (tb, cb) = reads[0][i], reads[1][i]
            i += 1
            out.append(box and {"text": ta, "alt": tb, "agree": _norm(ta) == _norm(tb),
                                "conf": min(ca, cb), "box": box})
        rows.append(out)
    return _review(scaled, rows, grid)


### -- segmentation ----------------------------------------------------

def _line_masks(bw):
    h, w = bw.shape
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(w // 6, 20), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(h // 3, 15)))
    return cv2.morphologyEx(bw, cv2.MORPH_OPEN, hk), cv2.morphologyEx(bw, cv2.MORPH_OPEN, vk)


def _runs(on):
    """(start, end) of each run of True."""
    out, start = [], None
    for i, v in enumerate(np.append(on, False)):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i - 1))
            start = None
    return out


def _peaks(profile, frac=0.5):
    if not profile.max():
        return []
    return [int(np.mean(r)) for r in _runs(profile > frac * profile.max())]


def _bands(on, min_gap=2, min_h=6):
    """Runs of inked scanlines, merging gaps shorter than min_gap."""
    out = []
    for start, end in _runs(on):
        if out and start - out[-1][1] - 1 <= min_gap:
            out[-1] = (out[-1][0], end)
        else:
            out.append((start, end))
    return [(a, b) for a, b in out if b - a + 1 >= min_h]


def _segment(gray):
    """-> (scaled image, same with rules erased, rows of cell boxes or
    None for empty cells, has-grid flag)."""
    gray = cv2.resize(gray, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_CUBIC)
    h, w = gray.shape
    bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    hm, vm = _line_masks(bw)

    ### columns from the vertical rules; with fewer than two there's no
    ### grid to trust, so the whole width is one column
    cols = _peaks(vm.sum(0))
    grid = len(cols) >= 2
    if not grid:
        cols = [0, w - 1]
    hlines = _peaks(hm.sum(1))
    top, bottom = (hlines[0], hlines[-1]) if len(hlines) >= 2 else (0, h - 1)

    clean = gray.copy()
    clean[cv2.dilate(hm | vm, np.ones((2 * SCALE + 1, 2 * SCALE + 1), np.uint8)) > 0] = 255
    ink = cv2.threshold(clean, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    ink = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))  # drop specks
    ### only what's inside the table's outer border counts
    mask = np.zeros_like(ink)
    mask[top:bottom + 1, cols[0] + 3:cols[-1] - 2] = 255
    ink &= mask

    ### rows come from the text, not the row rules -- those often cut
    ### through glyphs. Each band grows halfway into the gaps around it
    ### so descenders (commas, g, y) aren't cropped off.
    bands = _bands((ink > 0).sum(1) >= 3 * SCALE)
    if not bands:
        return gray, clean, [], grid
    edges = [top] + [(a[1] + b[0]) // 2 for a, b in zip(bands, bands[1:])] + [bottom + 1]

    inset = 2 * SCALE
    rows = []
    for y0, y1 in zip(edges, edges[1:]):
        row = []
        for x0, x1 in zip(cols, cols[1:]):
            box = (y0, y1, x0 + inset, max(x1 - inset, x0 + inset + 1))
            has_ink = (ink[y0:y1, box[2]:box[3]] > 0).sum() >= 20 * SCALE
            row.append(box if has_ink else None)
        rows.append(row)
    return gray, clean, rows, grid


def _padded(cell):
    """Tight crop around the ink plus generous artificial whitespace."""
    ys, xs = np.nonzero(cell < 160)
    if len(ys):
        cell = cell[max(ys.min() - 3, 0):ys.max() + 4, max(xs.min() - 3, 0):xs.max() + 4]
    cell = cv2.copyMakeBorder(cell, PAD, PAD, PAD, PAD, cv2.BORDER_CONSTANT, value=255)
    return cv2.cvtColor(cell, cv2.COLOR_GRAY2BGR)


def _recognize(rec, crops):
    """(text, score) per crop. One crop per call: batching pads every
    crop to the widest in the batch, which measurably hurts accuracy."""
    from rapidocr.ch_ppocr_rec import TextRecInput

    out = []
    for crop in crops:
        if crop is None:
            out.append(("", 1.0))
            continue
        res = rec(TextRecInput(img=[crop]))
        ### both models can emit CJK; source tables here are Latin
        out.append(("".join(ch for ch in res.txts[0] if ch.isascii()).strip(), float(res.scores[0])))
    return out


### -- review rules ----------------------------------------------------

### Both models read a 2-px comma tail as a period, so voting can't
### catch it. A period followed by a space inside a word-run is a misread
### comma here (decimals like 9.5 have no space).
_PERIOD_SPACE = re.compile(r"(?<=[A-Za-z])\. (?=\S)")
### Lowercase in a digit-led token ("9.5mm", "70Mm") -- a case misread in
### all-caps unit styles. Flagged, never changed.
_CASE_SUSPECT = re.compile(r"\d[A-Z]*[a-z]")


def _norm(s):
    """Comparison form: the two models agree if these match."""
    if OCR_PERIOD_TO_COMMA:
        s = _PERIOD_SPACE.sub(", ", s)
    return re.sub(r"\s+", " ", s).strip().upper()


def _shape(s):
    """'416-7606Y1' -> '999-9999A9': a cell's character-class pattern."""
    return re.sub(r"[A-Za-z]", "A", re.sub(r"\d", "9", s.replace(" ", "")))


def _review(scaled, rows, grid):
    texts = [[c["text"] if c else "" for c in row] for row in rows]
    has_header = len(rows) >= 2 and not any(re.fullmatch(r"[\d\s.,-]+", t) for t in texts[0] if t)
    if has_header:
        for c, t in enumerate(texts[0]):
            match = difflib.get_close_matches(_norm(t), OCR_KNOWN_HEADERS, n=1, cutoff=0.6)
            if match:
                texts[0][c] = match[0]
    body_start = 1 if has_header else 0
    body = rows[body_start:]
    ncols = len(rows[0])

    flags, fixed = {}, []

    def add(r, c, why):
        key = f"{r},{c}"
        cell = body[r][c]
        entry = flags.setdefault(key, {"why": [], "alt": "", "crop": ""})
        if why not in entry["why"]:
            entry["why"].append(why)
        if cell:
            if not cell["agree"]:
                entry["alt"] = cell["alt"]
            y0, y1, x0, x1 = cell["box"]
            entry["crop"] = entry["crop"] or base64.b64encode(
                cv2.imencode(".png", scaled[y0:y1, x0:x1])[1]).decode()

    for c in range(ncols):
        col = [(r, row[c]) for r, row in enumerate(body)]
        vals = [texts[body_start + r][c] for r, _ in col]
        filled = [v for v in vals if v]

        ### a column that's mostly integers (item no., qty) -- the rest
        ### should be too; and if it counts up by one, gaps are misreads
        ints = [v for v in filled if v.isdigit()]
        numeric = filled and len(ints) / len(filled) >= 0.8
        ### a column that mostly shares one character pattern (part
        ### numbers) -- outliers are suspect
        shapes = Counter(_shape(v) for v in filled)
        common, common_n = shapes.most_common(1)[0] if shapes else ("", 0)
        patterned = not numeric and len(filled) >= 3 and common_n / len(filled) >= 0.7 and len(common) >= 4
        counting = numeric and len(ints) >= 3 and sum(
            int(b) - int(a) == 1 for a, b in zip(ints, ints[1:])) >= (len(ints) - 1) * 0.7

        prev = None
        for (r, cell), v in zip(col, vals):
            if cell is None:
                continue
            if not grid:
                add(r, c, "no table grid found")
            if not cell["agree"]:
                add(r, c, "models disagree")
            elif cell["conf"] < CONF_MIN:
                add(r, c, f"low confidence ({cell['conf']:.2f})")
            if numeric and not v.isdigit():
                add(r, c, "expected a number")
            if counting and v.isdigit():
                if prev is not None and int(v) != prev + 1:
                    add(r, c, f"sequence {prev} → {v}")
                prev = int(v)
            if patterned and _shape(v) != common:
                add(r, c, "doesn't match column pattern")
            if not numeric and not patterned:
                if OCR_PERIOD_TO_COMMA and _PERIOD_SPACE.search(v):
                    texts[body_start + r][c] = _PERIOD_SPACE.sub(", ", v)
                    fixed.append(f"{r},{c}")
                if _CASE_SUSPECT.search(v):
                    add(r, c, "check upper/lower case")

    return {
        "header": texts[0] if has_header else None,
        "body": texts[body_start:],
        "flags": flags,
        "fixed": fixed,
        "grid": grid,
    }
