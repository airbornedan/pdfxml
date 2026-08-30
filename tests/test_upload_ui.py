"""The upload page has no button -- choosing a PDF submits it. Self-skips
without a browser (`python -m playwright install chromium`)."""
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
    doc.new_page(width=300, height=400).insert_text((40, 80), "hello", fontsize=20)
    doc.new_page(width=300, height=400)
    data = doc.tobytes()
    doc.close()
    return data


def test_choosing_a_pdf_submits_it(browser, live_url):
    pg = browser.new_page()
    pg.goto(f"{live_url}/extract/pdf")
    assert pg.get_by_role("button", name="Upload").count() == 0
    with pg.expect_navigation(url=f"{live_url}/extract/page", timeout=5000):
        pg.set_input_files("#pdf-file",
                           files=[{"name": "t.pdf", "mimeType": "application/pdf", "buffer": _pdf()}])
    pg.close()


def test_non_pdf_stays_put_with_an_inline_error(browser, live_url):
    pg = browser.new_page()
    pg.goto(f"{live_url}/extract/pdf")
    pg.set_input_files("#pdf-file",
                       files=[{"name": "t.txt", "mimeType": "text/plain", "buffer": b"nope"}])
    pg.wait_for_timeout(300)
    assert pg.url.endswith("/extract/pdf")
    assert pg.locator("#file-error").is_visible()
    assert "doesn't look like a PDF" in pg.locator("#file-error").inner_text()
    pg.close()
