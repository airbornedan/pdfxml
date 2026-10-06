"""OCR of tables that are only a picture (app/ocr.py + the extract flow).
Ground truth the same way it's checked by hand: a real text table and a
PNG of that same table -- the text is what OCR has to reproduce."""
import html
import io
import re

import cv2
import fitz
import numpy as np
import pytest

from app import ocr, pdfops
from app.extensions import OCR_MODEL_DIR

pytestmark = pytest.mark.skipif(
    not all((OCR_MODEL_DIR / f).is_file() for f in ocr.MODEL_FILES), reason="OCR models not vendored"
)

HEADER = ["ITEM NO.", "PART NUMBER", "DESCRIPTION", "QTY"]
ROWS = [
    ["1", "416-7606Y1", "Nut, M6 Flanged locknut KK54758", "4"],
    ["2", "416-7601Y1", "Washer, M8 X 24 X 2MM", "4"],
    ["3", "416-6961Y1", "Bolt, M6X1.0X20 Flanged 19M7862", "4"],
    ["4", "416-7565Y1", "Hopper Assembly - RH", "1"],
    ["5", "416-7720Y1", "Bracket, Cradle Hopper with Smart Access", "1"],
]
COLS = [72, 132, 212, 470, 510]     # vertical rules, PDF points
TOP, ROW_H = 100, 13                # tight rows -- text nearly touches the rules
TABLE_RECT = (COLS[0] - 4, TOP - 4, COLS[-1] + 4, TOP + ROW_H * (len(ROWS) + 1) + 4)


def _draw_table(page):
    bottom = TOP + ROW_H * (len(ROWS) + 1)
    for x in COLS:
        page.draw_line((x, TOP), (x, bottom), width=0.8)
    for i in range(len(ROWS) + 2):
        page.draw_line((COLS[0], TOP + i * ROW_H), (COLS[-1], TOP + i * ROW_H), width=0.8)
    for r, row in enumerate([HEADER] + ROWS):
        for c, text in enumerate(row):
            page.insert_text((COLS[c] + 2, TOP + (r + 1) * ROW_H - 3), text, fontsize=9, fontname="helv")


def _text_table_pdf():
    doc = fitz.open()
    _draw_table(doc.new_page(width=612, height=792))
    return doc


def _image_table_pdf(dpi=110):
    """The same table, but only as a picture -- no text layer."""
    src = _text_table_pdf()
    png = src[0].get_pixmap(clip=fitz.Rect(TABLE_RECT), dpi=dpi, colorspace=fitz.csGRAY).tobytes("png")
    src.close()
    doc = fitz.open()
    doc.new_page(width=612, height=792).insert_image(fitz.Rect(TABLE_RECT), stream=png)
    return doc.tobytes()


@pytest.fixture(scope="module")
def image_pdf(tmp_path_factory):
    path = tmp_path_factory.mktemp("ocr") / "image_table.pdf"
    path.write_bytes(_image_table_pdf())
    return str(path)


def test_image_table_triggers_ocr_but_text_table_does_not(image_pdf, tmp_path):
    text_pdf = tmp_path / "text_table.pdf"
    _text_table_pdf().save(str(text_pdf))
    assert pdfops.extract_region(image_pdf, 0, TABLE_RECT, "table") == {"element_type": "table", "needs_ocr": True}
    assert "needs_ocr" not in pdfops.extract_region(str(text_pdf), 0, TABLE_RECT, "table")


def test_region_pixels_are_the_embedded_image_not_a_render(image_pdf):
    png = pdfops.region_ocr_png(image_pdf, 0, TABLE_RECT, 50)
    with fitz.open(image_pdf) as doc:
        xref = doc[0].get_images()[0][0]
        native = fitz.Pixmap(doc, xref)
    got = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
    assert got.shape == (native.height, native.width)


def test_ocr_matches_the_text_table_or_flags_the_difference(image_pdf):
    """Every cell is right, or wrong and flagged -- never wrong and silent."""
    table = ocr.read_table(pdfops.region_ocr_png(image_pdf, 0, TABLE_RECT, 50))
    assert table["grid"]
    assert table["header"] == HEADER
    assert len(table["body"]) == len(ROWS)
    silent = [
        (r, c, got, want)
        for r, (got_row, want_row) in enumerate(zip(table["body"], ROWS))
        for c, (got, want) in enumerate(zip(got_row, want_row))
        if got != want and f"{r},{c}" not in table["flags"]
    ]
    assert silent == []


### -- review rules, on hand-made model output --------------------------

def _cell(text, alt=None, conf=0.99):
    return {"text": text, "alt": text if alt is None else alt, "agree": alt is None or alt == text,
            "conf": conf, "box": (0, 4, 0, 4)}


def _review(rows, grid=True):
    return ocr._review(np.full((4, 4), 255, np.uint8), [[_cell(t) if isinstance(t, str) else t for t in row]
                                                         for row in rows], grid)


def test_review_restores_commas_and_flags_case():
    out = _review([["ITEM NO.", "DESCRIPTION"], ["1", "Nut. M16"], ["2", "Spacer, 9.5mm LG"], ["3", "Bolt, 1.0X20"]])
    assert out["body"][0][1] == "Nut, M16"
    assert "0,1" in out["fixed"]
    assert out["body"][2][1] == "Bolt, 1.0X20"          # decimals untouched
    assert "check upper/lower case" in out["flags"]["1,1"]["why"]


def test_review_flags_disagreement_low_confidence_and_breaks_in_a_column():
    out = _review([
        ["ITEM NO.", "PART NUMBER", "QTY"],
        ["1", "416-7606Y1", "4"],
        ["2", _cell("416-7601Y1", alt="416-7601YI"), "4"],
        ["4", "416-6961Y1", _cell("l", conf=0.5)],
        ["5", "416-756SY1", "1"],
        ["6", "416-7720Y1", "1"],
        ["7", "416-7202Y1", "2"],
        ["8", "416-7607Y1", "2"],
    ])
    flags = out["flags"]
    assert "models disagree" in flags["1,1"]["why"] and flags["1,1"]["alt"] == "416-7601YI"
    assert "sequence 2 → 4" in flags["2,0"]["why"]
    assert "expected a number" in flags["2,2"]["why"]
    assert any(w.startswith("low confidence") for w in flags["2,2"]["why"])
    assert "doesn't match column pattern" in flags["3,1"]["why"]
    assert "0,0" not in flags and "0,1" not in flags


def test_review_snaps_drifted_headers():
    out = _review([["ITem nO.", "PARt nUMBER", "DESCRIPION", "QiY"], ["1", "416-7606Y1", "Nut", "4"]])
    assert out["header"] == HEADER


def test_review_without_a_grid_flags_every_cell():
    out = _review([["Some text"], ["More text"]], grid=False)
    assert all("no table grid found" in f["why"] for f in out["flags"].values())
    assert len(out["flags"]) == len(out["body"])


### -- the extract flow -------------------------------------------------

@pytest.fixture
def ocr_loaded(client):
    r = client.post("/upload", data={"pdf": (io.BytesIO(_image_table_pdf()), "table.pdf")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    return client


def _select_table(client):
    x0, y0, x1, y1 = (v * 1.5 for v in TABLE_RECT)    # PREVIEW_ZOOM -- form coords are preview px
    return client.post("/extract/select", data={"element_type": "table", "x0": x0, "y0": y0, "x1": x1, "y1": y1})


def test_table_with_no_text_layer_shows_the_ocr_warning_first(ocr_loaded):
    r = _select_table(ocr_loaded)
    assert r.status_code == 302 and r.headers["Location"].endswith("/extract/select")
    page = ocr_loaded.get("/extract/select").data.decode()
    assert 'id="ocr-modal"' in page
    assert "This table is a picture, not text." in page


def test_ocr_result_page_says_ocr_shows_region_and_gates_the_xml(ocr_loaded):
    _select_table(ocr_loaded)
    assert ocr_loaded.post("/extract/ocr").status_code == 204
    page = ocr_loaded.get("/extract/result").data.decode()
    assert "Read by OCR." in page
    assert 'src="/extract/region-image?i=0"' in page
    from app.extensions import load_result
    with ocr_loaded.session_transaction() as sess:
        result = load_result(sess["pdf_token"])
    if result["ocr"]["flags"]:
        assert 'id="xml-output"' not in page
        assert 'name="ok-' in page
    else:
        assert 'id="xml-output"' in page
    assert ocr_loaded.get("/extract/region-image?i=0").mimetype == "image/png"


def test_ocr_only_runs_for_a_pending_selection(ocr_loaded):
    assert ocr_loaded.post("/extract/ocr").status_code == 409


def _force_flags(client, flags):
    from app.extensions import load_result, save_result
    with client.session_transaction() as sess:
        token = sess["pdf_token"]
    result = load_result(token)
    result["ocr"]["flags"] = {k: {"why": ["test"], "alt": "", "crop": ""} for k in flags}
    result["ocr"]["reviewed"] = False
    save_result(token, result)


def test_review_needs_every_flag_ticked_then_applies_edits(ocr_loaded):
    _select_table(ocr_loaded)
    ocr_loaded.post("/extract/ocr")
    _force_flags(ocr_loaded, ["0,2", "3,1"])

    partial = {"ok-0-2": "1", "cell-0-2": "Nut, M6 Flanged locknut KK54758", "cell-3-1": "x"}
    assert ocr_loaded.post("/extract/ocr-review", data=partial).status_code == 400

    full = dict(partial, **{"ok-3-1": "1", "cell-3-1": "  416-7565Y1 "})
    assert ocr_loaded.post("/extract/ocr-review", data=full).status_code == 302
    page = ocr_loaded.get("/extract/result").data.decode()
    assert 'id="xml-output"' in page
    assert "You checked all 2 highlighted cells." in page
    xml = html.unescape(re.search(r'id="xml-output">(.*?)</textarea>', page, re.S).group(1))
    assert "<para>416-7565Y1</para>" in xml


def test_text_results_show_the_selected_region_but_no_ocr_banner(client, sample_pdf):
    with open(sample_pdf, "rb") as f:
        client.post("/upload", data={"pdf": (io.BytesIO(f.read()), "sample.pdf")},
                    content_type="multipart/form-data")
    client.post("/extract/page", data={"page_number": "1"})
    client.post("/extract/select", data={"element_type": "paragraph", "x0": 100, "y0": 120, "x1": 800, "y1": 170})
    page = client.get("/extract/result").data.decode()
    assert 'src="/extract/region-image?i=0"' in page
    assert "Read by OCR." not in page
