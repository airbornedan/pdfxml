"""Full extraction wizard against a generated PDF (sandbox runs for real)."""
import io
import html
import json

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
