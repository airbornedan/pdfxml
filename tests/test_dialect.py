"""app/dialect.py -- translate foreign-but-equivalent tags in place,
before app/lml.py's structural checks run."""
from app.dialect import translate


def test_bold_and_italic_become_emphasis_anywhere():
    out, translated, problems = translate("<para>See <b>this</b> and <i>that</i>.</para>")
    assert out == '<para>See <emphasis role="strong">this</emphasis> and <emphasis>that</emphasis>.</para>'
    assert translated and not problems


def test_strong_and_em_are_also_recognized():
    out, translated, _ = translate("<para><strong>a</strong><em>b</em></para>")
    assert '<emphasis role="strong">a</emphasis>' in out
    assert "<emphasis>b</emphasis>" in out


def test_empty_bold_tag_is_dropped():
    out, translated, _ = translate("<para>a<b/>b</para>")
    assert out == "<para>ab</para>"
    assert translated


def test_html_list_nested_in_a_section_is_translated_in_place():
    src = (
        "<section>\n"
        "  <title>T</title>\n"
        "  <ul>\n"
        "    <li>first</li>\n"
        "    <li>second</li>\n"
        "  </ul>\n"
        "</section>"
    )
    out, translated, problems = translate(src)
    assert not problems and translated
    assert "<itemizedlist>" in out and "<listitem>" in out
    assert "<ul>" not in out and "<li>" not in out
    # everything outside the list is untouched, including its indentation
    assert out.startswith("<section>\n  <title>T</title>\n")
    assert out.rstrip().endswith("</section>")


def test_nested_html_list_inside_an_already_correct_listitem_is_translated():
    src = (
        "<orderedlist>\n"
        "  <listitem>\n"
        "    <para>a</para>\n"
        "    <ul><li>nested</li></ul>\n"
        "  </listitem>\n"
        "</orderedlist>"
    )
    out, translated, problems = translate(src)
    assert not problems and translated
    assert "<itemizedlist>" in out
    # the outer, already-correct list is untouched
    assert out.count("<orderedlist>") == 1 and out.count("<listitem>") == 2


def test_already_correct_dialect_is_left_completely_alone():
    src = (
        "<section>\n  <title>T</title>\n"
        "  <orderedlist>\n    <listitem>\n      <para>a</para>\n    </listitem>\n  </orderedlist>\n"
        "  <informaltable frame=\"box\" rules=\"all\">\n"
        "    <tbody><tr><td><para>x</para></td></tr></tbody>\n"
        "  </informaltable>\n</section>"
    )
    out, translated, problems = translate(src)
    assert out == src
    assert not translated and not problems


def test_cals_table_anywhere_is_translated_to_html_model():
    src = (
        "<section><title>T</title>\n"
        "  <informaltable><tgroup cols=\"2\">"
        "<thead><row><entry>A</entry><entry>B</entry></row></thead>"
        "<tbody><row><entry>1</entry><entry>2</entry></row></tbody>"
        "</tgroup></informaltable>\n"
        "</section>"
    )
    out, translated, problems = translate(src)
    assert not problems and translated
    assert "<tgroup" not in out and "<row>" not in out and "<entry>" not in out
    assert "<th>" in out and "<td>" in out


def test_html_table_without_cals_is_left_alone():
    # plain tr/td is already Paligo's own dialect -- lml.py's own table
    # checks handle missing <para> wraps etc., dialect.py has no reason to
    # touch it.
    src = "<informaltable><tbody><tr><td>x</td></tr></tbody></informaltable>"
    out, translated, problems = translate(src)
    assert out == src
    assert not translated and not problems


def test_list_item_containing_a_table_bails_with_a_line_number():
    src = "<section><title>T</title>\n<ul><li>see <table><tr><td>x</td></tr></table></li></ul>\n</section>"
    out, translated, problems = translate(src)
    assert out == src  # untouched -- couldn't translate safely
    assert not translated
    assert problems and problems[0]["line"] == 2
    assert "restructure" in problems[0]["message"]


def test_cals_spans_bail_with_a_line_number():
    src = (
        "<section><title>T</title>\n"
        "<informaltable><tgroup cols=\"2\"><tbody>"
        "<row><entry namest=\"c1\" nameend=\"c2\">wide</entry></row>"
        "</tbody></tgroup></informaltable>\n</section>"
    )
    out, translated, problems = translate(src)
    assert out == src
    assert not translated
    assert problems and "by hand" in problems[0]["message"]


def test_plain_text_with_nothing_foreign_is_unchanged():
    src = "<section><title>T</title><para>just prose</para></section>"
    out, translated, problems = translate(src)
    assert out == src and not translated and not problems


# --- folded into /check ---

def test_check_translates_html_list_and_reports_it_clean(client):
    src = "<section><title>T</title><ul><li>first</li><li>second</li></ul></section>"
    r = client.post("/check", data={"xml": src})
    body = r.data.decode()
    assert "No problems found" in body
    assert "&lt;itemizedlist&gt;" in body
    assert "Translated" in body


def test_check_surfaces_a_dialect_bail_as_a_finding(client):
    src = "<section><title>T</title>\n<ul><li>see <table><tr><td>x</td></tr></table></li></ul>\n</section>"
    r = client.post("/check", data={"xml": src})
    body = r.data.decode()
    assert "restructure" in body
    assert "line 2" in body
