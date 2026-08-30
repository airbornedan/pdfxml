"""Full extraction wizard against a generated PDF (sandbox runs for real)."""
import io
import html

import pytest


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


def test_render_routes(loaded):
    for path in ("/extract/thumbnail", "/extract/page-thumbnail?page=1", "/extract/page-image"):
        r = loaded.get(path)
        assert r.status_code == 200 and r.mimetype == "image/png"
        assert len(r.data) > 100


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


def test_extract_list(loaded):
    r = loaded.post("/extract/select",
                    data={"element_type": "list", "x0": "60", "y0": "500", "x1": "870", "y1": "1000"},
                    follow_redirects=True)
    assert r.status_code == 200
    assert b"itemizedlist" in r.data
    assert b"first bullet item" in r.data


def test_extract_image_returns_png(loaded):
    r = loaded.post("/extract/select",
                    data={"element_type": "image", "x0": "40", "y0": "40", "x1": "870", "y1": "1000"},
                    follow_redirects=True)
    assert r.status_code == 200
    img = loaded.get("/extract/image")
    assert img.status_code == 200 and img.mimetype == "image/png"


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
