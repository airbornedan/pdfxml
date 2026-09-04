import base64
import re

import fitz


def test_home_has_screenshot_card(client):
    body = client.get("/").data.decode()
    assert 'Screenshot' in body
    assert 'href="/screenshot"' in body
    assert 'images/screenshot.svg' in body


def test_screenshot_upload_returns_fixed_crop(client, tmp_path):
    source = tmp_path / "sample.png"
    document = fitz.open()
    document.new_page(width=1920, height=1080).get_pixmap().save(str(source))
    document.close()
    with open(source, "rb") as image:
        response = client.post(
            "/screenshot",
            data={"image": (image, "sample.png")},
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    match = re.search(rb'data:image/png;base64,([^" ]+)', response.data)
    assert match
    cropped = fitz.Pixmap(base64.b64decode(match.group(1)))
    assert (cropped.width, cropped.height) == (1178, 1072)
    assert b"onclick=" not in response.data


def test_screenshot_rejects_non_image(client):
    response = client.post(
        "/screenshot",
        data={"image": (b"not an image", "notes.txt")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert b"doesn't look like a PNG or JPEG" in response.data