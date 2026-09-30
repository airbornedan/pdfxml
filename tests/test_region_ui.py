"""Headless check of the region select box: it can be resized by its
handles and moved by dragging inside, and it comes back after an
extraction. Self-skips without a browser (`python -m playwright install
chromium`)."""
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


def _pdf():
    doc = fitz.open()
    doc.new_page(width=612, height=792).insert_text((72, 100), "A paragraph to select.", fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def page(browser, live_url):
    pg = browser.new_page(viewport={"width": 1000, "height": 900})
    pg._errors = []
    pg.on("console", lambda m: pg._errors.append(m.text)
          if ("Content Security Policy" in m.text or "Refused to" in m.text) else None)
    pg.on("pageerror", lambda e: pg._errors.append(f"pageerror: {e}"))
    pg.goto(f"{live_url}/extract/pdf")
    # single page -- upload lands straight on select_region
    with pg.expect_navigation(url=f"{live_url}/extract/select", timeout=5000):
        pg.set_input_files("#pdf-file",
                           files=[{"name": "t.pdf", "mimeType": "application/pdf", "buffer": _pdf()}])
    pg.wait_for_function("() => document.getElementById('page-image').naturalWidth > 0")
    yield pg
    assert not pg._errors, pg._errors
    pg.close()


def _drag(page, x0, y0, x1, y1):
    page.mouse.move(x0, y0)
    page.mouse.down()
    page.mouse.move(x1, y1, steps=5)
    page.mouse.up()


def _fields(page):
    return [float(page.input_value(f"#{k}")) for k in ("x0", "y0", "x1", "y1")]


def _center(page, selector):
    b = page.locator(selector).bounding_box()
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


def test_region_resizes_moves_and_survives_a_round_trip(page):
    img = page.locator("#page-image").bounding_box()
    ox, oy = img["x"], img["y"]
    _drag(page, ox + 50, oy + 50, ox + 250, oy + 150)
    drawn = _fields(page)
    assert drawn[2] > drawn[0] and drawn[3] > drawn[1]
    assert page.locator(".extract-btn[value='paragraph']").first.is_enabled()

    # the grips are big enough to grab
    grip = page.locator(".select-handle[data-h='se']").bounding_box()
    assert grip["width"] >= 18 and grip["height"] >= 18

    # bottom-right grip grows the box; the top-left corner stays put
    hx, hy = _center(page, ".select-handle[data-h='se']")
    _drag(page, hx, hy, hx + 60, hy + 40)
    grown = _fields(page)
    assert grown[:2] == pytest.approx(drawn[:2])
    assert grown[2] > drawn[2] and grown[3] > drawn[3]

    # an edge grip moves only its edge
    hx, hy = _center(page, ".select-handle[data-h='w']")
    _drag(page, hx, hy, hx - 30, hy + 25)
    widened = _fields(page)
    assert widened[0] < grown[0]
    assert widened[1:] == pytest.approx(grown[1:])

    # dragging inside moves it without changing its size
    cx, cy = _center(page, "#select-box")
    _drag(page, cx, cy, cx + 40, cy + 30)
    moved = _fields(page)
    assert moved[0] > widened[0] and moved[1] > widened[1]
    assert moved[2] - moved[0] == pytest.approx(widened[2] - widened[0])
    assert moved[3] - moved[1] == pytest.approx(widened[3] - widened[1])

    # extract, then back from the result page: the same box is back,
    # ready to adjust
    with page.expect_navigation():
        page.locator(".extract-btn[value='paragraph']").first.click()
    with page.expect_navigation():
        page.get_by_role("button", name="Select new").first.click()
    page.wait_for_selector("#select-box:visible")
    assert _fields(page) == pytest.approx(moved)
    assert page.locator(".extract-btn[value='paragraph']").first.is_enabled()

    # Esc still clears it
    page.keyboard.press("Escape")
    assert not page.locator("#select-box").is_visible()
    assert page.locator(".extract-btn[value='paragraph']").first.is_disabled()


# the native folder picker can't be driven headless -- stand in a folder
# from the browser's private storage (OPFS), which has the same API
PICKER_STUB = """
window.showDirectoryPicker = async () => {
    const root = await navigator.storage.getDirectory();
    return root.getDirectoryHandle("picked", { create: true });
};
"""

READ_SAVED = """async (name) => {
    const root = await navigator.storage.getDirectory();
    const picked = await root.getDirectoryHandle("picked");
    const sub = await picked.getDirectoryHandle("t");
    const file = await (await sub.getFileHandle(name)).getFile();
    const head = new Uint8Array(await file.slice(0, 4).arrayBuffer());
    return { size: file.size, png: head[1] === 0x50 && head[2] === 0x4e && head[3] === 0x47 };
}"""


def test_save_png_writes_into_a_per_pdf_folder(page):
    page.add_init_script(PICKER_STUB)
    page.reload()
    page.wait_for_function("() => document.getElementById('page-image').naturalWidth > 0")
    assert "No save folder chosen yet" in page.locator("#image-save-folder").inner_text()

    img = page.locator("#page-image").bounding_box()
    _drag(page, img["x"] + 40, img["y"] + 40, img["x"] + 500, img["y"] + 560)
    page.locator(".extract-btn[value='image']").first.click()
    page.wait_for_selector("#image-modal:not(.is-hidden)")
    page.wait_for_function("() => document.getElementById('image-modal-img').complete")

    # the name stays the user's to choose
    page.fill("#image-modal-name", "my figure")
    page.click("#image-modal-download")
    page.wait_for_selector("#image-save-status:not(.is-hidden)")
    assert "Saved picked/t/my figure.png" in page.inner_text("#image-save-status")
    assert "Saving to picked/t/" in page.inner_text("#image-save-folder")
    saved = page.evaluate(READ_SAVED, "my figure.png")
    assert saved["png"] and saved["size"] > 0

    # same name again: warned first, replaced on the second Save --
    # with the watermarked (data: URL) version, which is a bigger file
    page.click("#image-modal-watermark")
    page.wait_for_function("() => document.getElementById('image-modal-download').href.startsWith('data:')")
    page.click("#image-modal-download")
    page.wait_for_function("() => document.getElementById('image-save-status').textContent.includes('already exists')")
    page.click("#image-modal-download")
    page.wait_for_function("() => document.getElementById('image-save-status').textContent.startsWith('Saved')")
    replaced = page.evaluate(READ_SAVED, "my figure.png")
    assert replaced["png"] and replaced["size"] != saved["size"]

    # the folder survives a reload (page arrows reload the page)
    page.reload()
    page.wait_for_function("() => document.getElementById('image-save-folder').textContent.includes('Saving to picked/t/')")


def test_save_png_falls_back_to_a_download_without_the_folder_api(page):
    # Firefox/Safari have no showDirectoryPicker
    page.add_init_script("delete window.showDirectoryPicker;")
    page.reload()
    page.wait_for_function("() => document.getElementById('page-image').naturalWidth > 0")
    assert not page.locator("#image-save-folder").is_visible()

    img = page.locator("#page-image").bounding_box()
    _drag(page, img["x"] + 40, img["y"] + 40, img["x"] + 300, img["y"] + 200)
    page.locator(".extract-btn[value='image']").first.click()
    page.wait_for_selector("#image-modal:not(.is-hidden)")
    with page.expect_download() as dl:
        page.click("#image-modal-download")
    assert dl.value.suggested_filename == "t-p1.png"
