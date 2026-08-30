"""Headless click-through of the image-crop flow: result shows in an
in-page modal (no popup), no CSP violations, and the selection state
machine survives a release outside the canvas and a stray click.
Self-skips without a browser (`python -m playwright install chromium`)."""
import fitz
import pytest

pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not available: {exc}")
        yield b
        b.close()


def _png(w=300, h=200):
    doc = fitz.open()
    doc.new_page(width=w, height=h).insert_text((20, 60), "crop me", fontsize=28)
    data = doc[0].get_pixmap().tobytes("png")
    doc.close()
    return data


@pytest.fixture
def page(browser, live_url, request):
    pg = browser.new_page(viewport={"width": 900, "height": 700})
    pg._violations = []
    pg.on("console", lambda m: pg._violations.append(m.text)
          if ("Content Security Policy" in m.text or "Refused to" in m.text) else None)
    pg.on("pageerror", lambda e: pg._violations.append(f"pageerror: {e}"))
    pg.on("dialog", lambda d: (pg._violations.append(f"unexpected dialog: {d.message}"), d.dismiss()))
    pg.goto(f"{live_url}/image-crop")
    big = request.node.get_closest_marker("big_image") is not None
    pg.set_input_files("#image-loader",
                       files=[{"name": "t.png", "mimeType": "image/png",
                               "buffer": _png(4000, 3000) if big else _png()}])
    pg.wait_for_selector("#canvas-wrap:visible", timeout=3000)
    yield pg
    assert not pg._violations, pg._violations
    pg.close()


def _drag(page, x0, y0, x1, y1, steps=4):
    box = page.locator("#crop-canvas").bounding_box()
    page.mouse.move(box["x"] + x0, box["y"] + y0)
    page.mouse.down()
    page.mouse.move(box["x"] + x1, box["y"] + y1, steps=steps)
    page.mouse.up()


def _crop(page):
    page.get_by_role("button", name="Crop selection").first.click()


def test_crop_shows_modal_result_no_popup(page):
    before = len(page.context.pages)
    _drag(page, 20, 20, 120, 90)
    _crop(page)

    page.wait_for_selector("#result-modal:visible", timeout=2000)
    src = page.locator("#result-img").get_attribute("src")
    assert src.startswith("data:image/png;base64,")
    dl = page.locator("#result-download")
    assert dl.get_attribute("download") == "t.png"   # defaults to the source file's name
    assert dl.get_attribute("href") == src
    assert len(page.context.pages) == before, "must not open a popup"


def test_result_filename_field_renames_the_download(page):
    _drag(page, 20, 20, 120, 90)
    _crop(page)
    page.wait_for_selector("#result-modal:visible", timeout=2000)
    dl = page.locator("#result-download")

    page.fill("#result-filename", "SPS-1234_diagram")
    assert dl.get_attribute("download") == "SPS-1234_diagram.png"

    page.fill("#result-filename", "with/bad:chars")   # path/illegal chars stripped
    assert dl.get_attribute("download") == "withbadchars.png"

    page.fill("#result-filename", "")                 # empty falls back
    assert dl.get_attribute("download") == "cropped.png"


@pytest.mark.big_image
def test_result_modal_is_in_view_for_a_large_image(page):
    # a 4000x3000 source makes the working canvas taller than the viewport
    _drag(page, 30, 30, 300, 220)
    _crop(page)
    page.locator("#result-modal").wait_for(state="visible", timeout=2000)
    vp = page.viewport_size
    card = page.locator("#result-modal .result-modal__card").bounding_box()
    assert 0 <= card["y"] and card["y"] + card["height"] <= vp["height"] + 1
    assert 0 <= card["x"] and card["x"] + card["width"] <= vp["width"] + 1


def test_result_modal_dismissal(page):
    _drag(page, 20, 20, 120, 90)
    _crop(page)
    page.wait_for_selector("#result-modal:visible", timeout=2000)

    page.get_by_role("button", name="Close").click()
    assert page.locator("#result-modal").is_hidden()

    _crop(page)                       # same selection still valid
    page.wait_for_selector("#result-modal:visible", timeout=2000)
    page.keyboard.press("Escape")
    assert page.locator("#result-modal").is_hidden()


def test_crop_without_selection_shows_inline_error(page):
    _crop(page)
    err = page.locator("#file-error")
    assert err.is_visible()
    assert "Draw a rectangle" in err.inner_text()
    assert page.locator("#result-modal").is_hidden()


def test_selection_survives_release_outside_canvas(page):
    box = page.locator("#crop-canvas").bounding_box()
    page.mouse.move(box["x"] + 30, box["y"] + 30)
    page.mouse.down()
    page.mouse.move(box["x"] + 150, box["y"] + 120, steps=3)
    page.mouse.move(box["x"] + box["width"] + 200, box["y"] + box["height"] + 200, steps=3)  # off-canvas
    page.mouse.up()                                                                          # released outside
    _crop(page)
    page.wait_for_selector("#result-modal:visible", timeout=2000)


def test_stray_click_after_drag_keeps_selection(page):
    _drag(page, 20, 20, 140, 110)
    box = page.locator("#crop-canvas").bounding_box()
    page.mouse.click(box["x"] + 200, box["y"] + 40)   # a plain click, no drag
    _crop(page)
    page.wait_for_selector("#result-modal:visible", timeout=2000)
    assert page.locator("#file-error").is_hidden()
