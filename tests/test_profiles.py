"""PDFXML_TRUSTED_NETWORK gates routes, nav, footer, and rate limiting."""


def test_hardened_serves_generic_process_hides_troubleshooting(client):
    assert client.get("/process").status_code == 200
    assert client.get("/troubleshooting").status_code == 404
    body = client.get("/").data.decode()
    assert ">Process<" in body and ">Extract<" in body and ">Crop<" in body
    assert ">Troubleshoot<" not in body and ">Help<" not in body
    # generic Process content, not the SurePoint tabs
    proc = client.get("/process").data.decode()
    assert ">Overview<" in proc and "Paligo" not in proc


def test_hardened_serves_site_pages_and_footer(client):
    assert client.get("/help").status_code == 404          # folded into /process
    for path in ("/terms", "/privacy"):
        assert client.get(path).status_code == 200
    foot = client.get("/").data.decode()
    assert "site-footer" in foot
    for href in ("/terms", "/privacy"):
        assert href in foot
    assert "/help" not in foot


def test_site_pages_do_not_leak_review_comments(client):
    for path in ("/terms", "/privacy"):
        body = client.get(path).data.decode()
        assert "REVIEW" not in body and "<!--" not in body


def test_terms_states_eu_exclusion(client):
    body = client.get("/terms").data.decode()
    assert "EU" in body and ("EEA" in body or "European" in body)


def test_trusted_serves_surepoint_process_and_troubleshooting(trusted_client):
    assert trusted_client.get("/process").status_code == 200
    assert trusted_client.get("/troubleshooting").status_code == 200
    assert trusted_client.get("/terms").status_code == 404
    body = trusted_client.get("/").data.decode()
    assert ">Process<" in body and ">Troubleshoot<" in body
    assert "site-footer" not in body
    # the SurePoint tabs, not the generic guide
    proc = trusted_client.get("/process").data.decode()
    assert ">Begin<" in proc and "Paligo" in proc


def test_trusted_shows_style_guide_link(client, trusted_client):
    assert "style-guide-link" not in client.get("/").data.decode()
    assert "style-guide-link" in trusted_client.get("/").data.decode()


def test_rate_limit_trips_when_hardened(client):
    resps = [client.post("/upload", data={}, content_type="multipart/form-data")
             for _ in range(13)]
    codes = [r.status_code for r in resps]
    assert 429 not in codes[:10]
    assert codes[10] == 429 and codes[12] == 429
    # friendly page, not the raw Werkzeug description
    body = resps[10].data.decode()
    assert "Slow down a moment" in body and "wait a minute" in body
    assert "exceeded an allotted request count" not in body


def test_no_rate_limit_when_trusted(trusted_client):
    codes = {trusted_client.post("/upload", data={}, content_type="multipart/form-data").status_code
             for _ in range(20)}
    assert 429 not in codes
