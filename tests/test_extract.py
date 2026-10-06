"""Full extraction wizard against a generated PDF (sandbox runs for real)."""
import html
import io
import json
import os

import fitz
import pytest

from app import docbook
from app.pdfops import (
    _inspect_page_streams,
    _redact_watermark,
    render_region_png,
    _temporary_watermark_document,
    _watermark_object_ids,
)


@pytest.fixture
def loaded(client, sample_pdf):
    with open(sample_pdf, "rb") as f:
        data = f.read()
    r = client.post("/upload", data={"pdf": (io.BytesIO(data), "sample.pdf")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    assert client.post("/extract/page", data={"page_number": "1"},
                       follow_redirects=True).status_code == 200
    return client


def test_upload_rejects_non_pdf(client):
    r = client.post("/upload", data={"pdf": (io.BytesIO(b"not a pdf"), "x.pdf")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    assert b"valid PDF" in r.data


def test_single_page_upload_skips_choose_page(client, tmp_path):
    path = tmp_path / "single.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "Only one page.", fontsize=12)
    doc.save(str(path))
    doc.close()

    with open(path, "rb") as f:
        data = f.read()

    r = client.post("/upload", data={"pdf": (io.BytesIO(data), "single.pdf")},
                    content_type="multipart/form-data", follow_redirects=True)

    assert r.status_code == 200
    assert b"Draw a region" in r.data
    assert b"Which page?" not in r.data
    assert b"Choose page" not in r.data


def test_select_region_breadcrumb_links_back_to_choose_page(loaded):
    response = loaded.get("/extract/select")

    assert response.status_code == 200
    assert b'href="/extract/page">Choose page</a>' in response.data
    assert response.data.index(b"Choose page") < response.data.index(b"Select region")


def test_home_shows_deployment_timestamp(client, monkeypatch, tmp_path):
    timestamp_path = tmp_path / "last_updated.txt"
    timestamp_path.write_text("09:42, 06/10/2026", encoding="ascii")
    monkeypatch.setattr("app.blueprints.extract.DEPLOYED_AT_PATH", timestamp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert b'class="last-updated">Last updated: 09:42, 06/10/2026</p>' in response.data


def test_render_routes(loaded):
    for path in ("/extract/thumbnail", "/extract/page-thumbnail?page=1", "/extract/page-image"):
        r = loaded.get(path)
        assert r.status_code == 200 and r.mimetype == "image/png"
        assert len(r.data) > 100


def test_watermark_helpers_inspect_and_identify_content_stream(tmp_path):
    path = tmp_path / "watermark.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((30, 60), "Body text", fontsize=12)
    page.insert_text((30, 120), "SurePoint Ag Systems", fontsize=12)
    xref = page.get_contents()[0]
    stream = doc.xref_stream(xref)
    stream = stream.replace(
        b"<53757265506f696e742041672053797374656d73>",
        b"<53757265506f696e7420416720>Tj [<53797374656d73>]TJ",
    )
    doc.update_stream(xref, stream)
    doc.save(str(path))
    doc.close()

    with fitz.open(str(path)) as inspected:
        page = inspected[0]
        streams = _inspect_page_streams(inspected, page)
        xrefs = _watermark_object_ids(inspected, page, "SurePoint Ag Systems")
        assert streams
        assert xrefs
        assert set(xrefs).issubset({record["xref"] for record in streams})
        assert _watermark_object_ids(inspected, page, "SurePoint Ag Systems", direction=(1.0, 0.0)) == xrefs
        assert _watermark_object_ids(inspected, page, "SurePoint Ag Systems", direction=(0.0, 1.0)) == []


def test_temporary_watermark_document_rewrites_only_watermark_operators(tmp_path):
    path = tmp_path / "watermark.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((30, 60), "Body text", fontsize=12)
    page.insert_text((30, 120), "SurePoint Ag Systems", fontsize=12)
    doc.save(str(path))
    doc.close()

    with _temporary_watermark_document(str(path), 0, "SurePoint Ag Systems") as rewritten:
        with fitz.open(rewritten) as cleaned:
            text = cleaned[0].get_text()
            assert "Body text" in text
            assert "SurePoint Ag Systems" not in text
        assert os.path.exists(rewritten)
    assert not os.path.exists(rewritten)

    with fitz.open(str(path)) as original:
        assert "SurePoint Ag Systems" in original[0].get_text()


def test_temporary_watermark_document_keeps_ambiguous_lines(tmp_path):
    path = tmp_path / "ambiguous-watermark.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((30, 30), "Body text", fontsize=12)
    page.insert_text((30, 60), "SurePoint Ag Systems", fontsize=12)
    page.insert_text((30, 120), "SurePoint Ag Systems", fontsize=12)
    doc.save(str(path))
    doc.close()

    with _temporary_watermark_document(str(path), 0, "SurePoint Ag Systems") as rewritten:
        with fitz.open(rewritten) as copied:
            text = copied[0].get_text()
            assert "Body text" in text
            assert text.count("SurePoint Ag Systems") == 2


def test_temporary_watermark_document_copies_pages_without_watermark(tmp_path):
    path = tmp_path / "no-watermark.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((30, 60), "Body text", fontsize=12)
    doc.save(str(path))
    doc.close()

    with _temporary_watermark_document(str(path), 0, "SurePoint Ag Systems") as rewritten:
        with fitz.open(rewritten) as copied:
            with fitz.open(str(path)) as original:
                assert copied[0].get_text() == original[0].get_text()


def test_render_region_uses_non_destructive_watermark_path(tmp_path):
    path = tmp_path / "render-watermark.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((30, 60), "Body text", fontsize=12)
    page.insert_text((30, 120), "SurePoint Ag Systems", fontsize=12)
    doc.save(str(path))
    doc.close()

    png = render_region_png(str(path), 0, (0, 0, 300, 200), 1, "SurePoint Ag Systems", 10)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    with fitz.open(str(path)) as original:
        assert "Body text" in original[0].get_text()
        assert "SurePoint Ag Systems" in original[0].get_text()


def test_render_region_succeeds_when_watermark_cannot_be_mapped(tmp_path, monkeypatch):
    path = tmp_path / "unmapped-watermark.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((30, 60), "Body text", fontsize=12)
    page.insert_text((30, 120), "SurePoint Ag Systems", fontsize=12)
    doc.save(str(path))
    doc.close()
    monkeypatch.setattr("app.pdfops._watermark_object_ids", lambda *_args: [])

    png = render_region_png(str(path), 0, (0, 0, 300, 200), 1, "SurePoint Ag Systems", 10)

    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_rotated_watermark_render_keeps_crossed_body_text(tmp_path):
    path = tmp_path / "rotated-watermark.pdf"
    doc = fitz.open()
    page = doc.new_page(width=500, height=300)
    page.insert_text((50, 125), "Body text above the diagram", fontsize=14)
    page.insert_text((50, 205), "Body text below the diagram", fontsize=14)
    page.insert_text((90, 175), "SurePoint Ag Systems", fontsize=16)
    xref = page.get_contents()[-1]
    stream = doc.xref_stream(xref).replace(
        b"1 0 0 1 90 125 Tm", b"0.707 0.707 -0.707 0.707 90 175 Tm"
    )
    doc.update_stream(xref, stream)
    doc.save(str(path))
    doc.close()

    with fitz.open(str(path)) as original:
        lines = [
            line
            for block in original[0].get_text("rawdict")["blocks"]
            for line in block.get("lines", [])
            if "".join(c["c"] for s in line.get("spans", []) for c in s.get("chars", []))
            == "SurePoint Ag Systems"
        ]
        assert len(lines) == 1
        watermark_direction = tuple(lines[0]["dir"])

    with _temporary_watermark_document(
        str(path), 0, "SurePoint Ag Systems", direction=watermark_direction
    ) as rewritten:
        with fitz.open(rewritten) as cleaned:
            text = cleaned[0].get_text()
            assert "Body text above the diagram" in text
            assert "Body text below the diagram" in text
            assert "SurePoint Ag Systems" not in text


def test_real_pdf_fixture_renders_without_text_loss():
    path = "tests/test.pdf"
    with fitz.open(path) as original:
        page_number = 19
        source_text = original[page_number].get_text()
        source_rect = tuple(original[page_number].rect)
        assert "SurePoint Ag Systems" in source_text
        assert "Row Monitoring Installation" in source_text

    with _temporary_watermark_document(path, page_number, "SurePoint Ag Systems") as rewritten:
        with fitz.open(rewritten) as copied:
            cleaned_text = copied[page_number].get_text()
            assert "SurePoint Ag Systems" not in cleaned_text
            assert "Row Monitoring Installation" in cleaned_text
            png = copied[page_number].get_pixmap(clip=fitz.Rect(*source_rect), matrix=fitz.Matrix(0.5, 0.5)).tobytes("png")

    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_continue_interstitial_thumbnail_links_to_choose_page(loaded):
    body = loaded.get("/extract/pdf").data.decode()
    assert "Continue with this PDF?" in body                 # interstitial, not the dropzone
    assert 'class="pdf-thumbnail-link"' in body
    assert body.count('href="/extract/page"') == 2           # thumbnail + button, same target


def test_page_thumbnail_out_of_range_is_404(loaded):
    assert loaded.get("/extract/page-thumbnail?page=999").status_code == 404


# submitted coords are preview-space = PDF points x PREVIEW_ZOOM (1.5);
# these boxes cover the top / bottom half of the 612x792pt page.
def test_extract_paragraph(loaded):
    r = loaded.post("/extract/select",
                    data={"element_type": "paragraph", "x0": "60", "y0": "60", "x1": "870", "y1": "450"},
                    follow_redirects=True)
    assert r.status_code == 200
    # result page shows the preview text; the XML fragment is HTML-escaped in a textarea
    assert b"plain paragraph of body text" in r.data
    assert b"&lt;para&gt;" in r.data
    assert r.data.count(b"&lt;para&gt;") == 1
    assert b'<textarea class="xml-output" id="xml-output">' in r.data


def test_extract_paragraph_splits_on_gap(loaded):
    assert loaded.post("/extract/page", data={"page_number": "2"},
                       follow_redirects=True).status_code == 200
    r = loaded.post("/extract/select",
                    data={"element_type": "paragraph", "x0": "60", "y0": "120", "x1": "870", "y1": "420"},
                    follow_redirects=True)
    body = r.data.decode()
    assert body.count("&lt;para&gt;") == 2                       # one per paragraph
    assert "line one of three, line two continues" in body       # 3 source lines joined
    assert "A second paragraph, clearly separated." in body


def test_extract_paragraph_keeps_bold_and_italic(loaded):
    assert loaded.post("/extract/page", data={"page_number": "3"},
                       follow_redirects=True).status_code == 200
    r = loaded.post("/extract/select",
                    data={"element_type": "paragraph", "x0": "60", "y0": "120", "x1": "870", "y1": "300"},
                    follow_redirects=True)
    xml = html.unescape(r.data.decode())               # fragment is HTML-escaped in a textarea
    assert '<emphasis role="strong">Enter</emphasis>' in xml
    assert '<emphasis>Esc</emphasis>' in xml


def test_extract_paragraph_flags_page_refs(loaded):
    assert loaded.post("/extract/page", data={"page_number": "4"},
                       follow_redirects=True).status_code == 200
    r = loaded.post("/extract/select",
                    data={"element_type": "paragraph", "x0": "60", "y0": "60", "x1": "870", "y1": "260"},
                    follow_redirects=True)
    body = r.data.decode()
    # flagged in the preview, kept verbatim in the copyable XML
    assert '<span class="page-ref-flag">(page 29)</span>' in body
    assert "Tighten the clamp (page 29) before moving" in html.unescape(body)


def test_extract_list(loaded):
    r = loaded.post("/extract/select",
                    data={"element_type": "list", "x0": "60", "y0": "500", "x1": "870", "y1": "1000"},
                    follow_redirects=True)
    assert r.status_code == 200
    assert b"itemizedlist" in r.data
    assert b"first bullet item" in r.data


def test_table_falls_back_to_ocr_and_returns_lml(loaded, monkeypatch):
    monkeypatch.setattr(
        "app.blueprints.extract.sandbox.run",
        lambda func, *args: func(*args),
    )
    monkeypatch.setattr(
        "app.docbook._ocr_table_rows",
        lambda _page, _rect: ([["Part", "Description"], ["A1", "Bolt"]], True),
    )

    response = loaded.post(
        "/extract/select",
        data={"element_type": "table", "x0": "60", "y0": "60", "x1": "870", "y1": "450"},
        follow_redirects=True,
    )

    body = response.data.decode()
    xml = html.unescape(body)
    compact_xml = "".join(xml.split())
    assert response.status_code == 200
    assert "OCR was used to reconstruct this table" in body
    assert '<informaltable frame="box" rules="all">' in xml
    assert "<th><para>Part</para></th>" in compact_xml
    assert "<td><para>Bolt</para></td>" in compact_xml
    assert "validation-pass" in body


def test_glyph_table_does_not_use_ocr(monkeypatch):
    document = fitz.open()
    page = document.new_page(width=300, height=200)
    table_rect = fitz.Rect(50, 50, 250, 130)
    page.draw_rect(table_rect)
    page.draw_line((150, 50), (150, 130))
    page.draw_line((50, 90), (250, 90))
    for position, text in (
        ((60, 75), "Part"),
        ((160, 75), "Description"),
        ((60, 115), "A1"),
        ((160, 115), "Bolt"),
    ):
        page.insert_text(position, text)
    monkeypatch.setattr(
        docbook,
        "_ocr_table_rows",
        lambda *_args: pytest.fail("OCR should not run when glyph table text is available"),
    )

    preview, xml, ocr_used = docbook.extract_table_with_ocr(page, table_rect)

    document.close()
    assert not ocr_used
    assert preview["body"]
    assert "Bolt" in xml


def test_extract_ordered_list_with_dot_paren_markers(loaded):
    assert loaded.post("/extract/page", data={"page_number": "5"},
                       follow_redirects=True).status_code == 200
    r = loaded.post("/extract/select",
                    data={"element_type": "list", "x0": "60", "y0": "60", "x1": "870", "y1": "360"},
                    follow_redirects=True)
    body = r.data.decode()
    assert "orderedlist" in body
    assert "Nothing could be converted" not in body
    for step in ("Press the HOME button", "Open the settings page", "Choose the device"):
        assert step in body
    assert body.count("&lt;listitem&gt;") == 3


def test_retry_restores_the_last_region(loaded):
    loaded.post("/extract/select",
                data={"element_type": "paragraph", "x0": "60", "y0": "60", "x1": "870", "y1": "450"},
                follow_redirects=True)
    body = loaded.get("/extract/select").data.decode()
    assert "const last = [60.0, 60.0, 870.0, 450.0];" in body
    assert 'class="select-handle" data-h="se"' in body


def test_last_region_not_restored_on_another_page(loaded):
    loaded.post("/extract/select",
                data={"element_type": "paragraph", "x0": "60", "y0": "60", "x1": "870", "y1": "450"},
                follow_redirects=True)
    body = loaded.post("/extract/page/next", follow_redirects=True).data.decode()
    assert "const last = null;" in body
    # back on its own page, it returns
    body = loaded.post("/extract/page/prev", follow_redirects=True).data.decode()
    assert "const last = [60.0, 60.0, 870.0, 450.0];" in body


def test_last_region_not_restored_while_continuing(loaded):
    loaded.post("/extract/select",
                data={"element_type": "list", "x0": "60", "y0": "500", "x1": "870", "y1": "1000"},
                follow_redirects=True)
    body = loaded.post("/extract/continue-more", follow_redirects=True).data.decode()
    assert "const last = null;" in body


def test_select_more_appends_without_leaving_the_page(loaded):
    # first pass: the 3-item bullet list on page 1
    r = loaded.post("/extract/select",
                    data={"element_type": "list", "x0": "60", "y0": "500", "x1": "870", "y1": "1000"},
                    follow_redirects=True)
    body = r.data.decode()
    assert body.count("&lt;listitem&gt;") == 3
    assert "Add to list" in body

    # "Add to list" arms continuation and returns to select_region on the
    # SAME page -- the builder panel appears, Table/Image are locked out
    r = loaded.post("/extract/continue-more", follow_redirects=True)
    body = r.data.decode()
    assert "3 items so far" in body                            # the builder panel
    assert "first bullet item" in body                         # its preview
    assert 'value="list"' in body
    assert 'name="element_type" value="table"' not in body
    assert 'name="element_type" value="image"' not in body
    assert "Page 1 of" in body                                 # did not advance a page

    # select the same list again -- items concatenate, still in the builder
    r = loaded.post("/extract/select",
                    data={"element_type": "list", "x0": "60", "y0": "500", "x1": "870", "y1": "1000"},
                    follow_redirects=True)
    body = r.data.decode()
    assert "6 items so far" in body                            # 3 + 3
    assert "Page 1 of" in body                                 # still on the same page

    # "Done" ends the builder and shows the assembled fragment
    r = loaded.post("/extract/continue-done", follow_redirects=True)
    body = r.data.decode()
    assert body.count("&lt;listitem&gt;") == 6
    assert "&lt;itemizedlist&gt;" in body


def test_select_more_survives_a_page_change(loaded):
    loaded.post("/extract/select",
                data={"element_type": "list", "x0": "60", "y0": "500", "x1": "870", "y1": "1000"},
                follow_redirects=True)
    loaded.post("/extract/continue-more", follow_redirects=True)
    # the page arrows carry the continuation onto another page
    r = loaded.post("/extract/page/next", follow_redirects=True)
    body = r.data.decode()
    assert "3 items so far" in body                            # builder still armed
    assert "Page 2 of" in body


def test_extract_more_type_mismatch_is_rejected(loaded):
    loaded.post("/extract/select",
               data={"element_type": "list", "x0": "60", "y0": "500", "x1": "870", "y1": "1000"},
               follow_redirects=True)
    loaded.post("/extract/continue-more", follow_redirects=True)
    r = loaded.post("/extract/select",
                    data={"element_type": "paragraph", "x0": "60", "y0": "60", "x1": "870", "y1": "450"})
    assert r.status_code == 400


def test_extract_more_hidden_without_prior_result(loaded):
    r = loaded.post("/extract/continue-more")
    assert r.status_code == 400


def test_select_more_offered_on_the_last_page(loaded):
    # no longer tied to "a next page exists" -- the list may continue in
    # another column on this same page
    assert loaded.post("/extract/page", data={"page_number": "5"},
                       follow_redirects=True).status_code == 200
    r = loaded.post("/extract/select",
                    data={"element_type": "list", "x0": "60", "y0": "60", "x1": "870", "y1": "360"},
                    follow_redirects=True)
    assert "Add to list" in r.data.decode()


def test_extract_image_returns_png(loaded):
    r = loaded.post("/extract/select",
                    data={"element_type": "image", "x0": "40", "y0": "40", "x1": "870", "y1": "1000"},
                    follow_redirects=True)
    assert r.status_code == 200
    img = loaded.get("/extract/image")
    assert img.status_code == 200 and img.mimetype == "image/png"


def test_image_result_warns_when_watermark_cannot_be_removed(loaded, monkeypatch):
    monkeypatch.setattr("app.blueprints.extract.sandbox.run", lambda *_args: False)
    response = loaded.post(
        "/extract/select",
        data={"element_type": "image", "x0": "40", "y0": "40", "x1": "870", "y1": "1000"},
        follow_redirects=True,
    )

    body = response.data.decode()
    assert response.status_code == 200
    assert "The PDF watermark could not be removed" in body
    assert 'class="extracted-image"' in body


def test_image_button_returns_204_and_saves_without_a_result_page(loaded):
    # the in-page flow POSTs with this header and expects no navigation
    r = loaded.post("/extract/select",
                    data={"element_type": "image", "x0": "40", "y0": "40", "x1": "870", "y1": "1000"},
                    headers={"X-Requested-With": "fetch"})
    assert r.status_code == 204 and r.data == b""
    assert loaded.get("/extract/image").mimetype == "image/png"


def test_select_region_page_carries_the_image_modal(loaded):
    body = loaded.get("/extract/select").data.decode()
    assert 'id="image-modal"' in body
    assert 'id="image-modal-name"' in body
    assert 'id="image-modal-watermark"' in body
    # default download name is built from the PDF filename + page number
    assert '"sample.pdf"' in body and '-p1"' in body


def test_invalid_element_type_is_400(loaded):
    r = loaded.post("/extract/select",
                    data={"element_type": "bogus", "x0": "1", "y0": "1", "x1": "9", "y1": "9"})
    assert r.status_code == 400


def test_extract_image_erase_rects_changes_output(loaded):
    # baseline: whole region, nothing erased
    r1 = loaded.post("/extract/select",
                    data={"element_type": "image", "x0": "40", "y0": "40", "x1": "870", "y1": "1000"},
                    headers={"X-Requested-With": "fetch"})
    assert r1.status_code == 204
    baseline = loaded.get("/extract/image").data

    # same region, but a swath over the first-page paragraph is punched white
    r2 = loaded.post("/extract/select",
                    data={
                        "element_type": "image", "x0": "40", "y0": "40", "x1": "870", "y1": "1000",
                        "erase_rects": json.dumps([[60, 130, 700, 180]]),
                    },
                    headers={"X-Requested-With": "fetch"})
    assert r2.status_code == 204
    erased = loaded.get("/extract/image").data
    assert erased != baseline


def test_watermark_redaction_keeps_other_text_on_matching_line():
    document = fitz.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 120), "BODY BEFORE SurePoint Ag Systems BODY AFTER", fontsize=18)

    _redact_watermark(page, "SurePoint Ag Systems")

    remaining = page.get_text("text")
    assert "BODY BEFORE" in remaining
    assert "BODY AFTER" in remaining
    assert "SurePoint Ag Systems" not in remaining
    document.close()


def test_extract_image_erase_rects_malformed_json_is_400(loaded):
    r = loaded.post("/extract/select",
                    data={
                        "element_type": "image", "x0": "40", "y0": "40", "x1": "870", "y1": "1000",
                        "erase_rects": "not json",
                    })
    assert r.status_code == 400


def test_extract_image_too_many_erase_rects_is_400(loaded):
    r = loaded.post("/extract/select",
                    data={
                        "element_type": "image", "x0": "40", "y0": "40", "x1": "870", "y1": "1000",
                        "erase_rects": json.dumps([[10, 10, 20, 20]] * 25),
                    })
    assert r.status_code == 400


def test_extract_image_erase_rects_ignored_for_non_image_types(loaded):
    # erase_rects only means something for images -- a list/paragraph
    # submission carrying it shouldn't be affected or rejected
    r = loaded.post("/extract/select",
                    data={
                        "element_type": "paragraph", "x0": "60", "y0": "60", "x1": "870", "y1": "450",
                        "erase_rects": json.dumps([[10, 10, 20, 20]]),
                    },
                    follow_redirects=True)
    assert r.status_code == 200
    assert b"plain paragraph of body text" in r.data
