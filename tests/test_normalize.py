"""app/paligo.py -- tag soup -> the dialect docbook.py emits / Paligo accepts."""
import re

from app.paligo import normalize
from app.docbook import validate_fragment


def _norm(src):
    out, changed, diag = normalize(src)
    return out, changed, diag


def test_html_ul_becomes_itemizedlist_with_para_wrapped_items():
    out, changed, _ = _norm("<ul><li>first</li><li>second</li></ul>")
    assert changed
    assert out.count("<listitem>") == 2
    assert out.count("<para>") == 2
    assert out.startswith("<itemizedlist>")
    assert validate_fragment(out)[0]


def test_html_ol_becomes_orderedlist():
    out, _, _ = _norm("<ol><li>step</li></ol>")
    assert out.startswith("<orderedlist>")


def test_bare_listitem_gets_a_para():
    out, changed, _ = _norm("<itemizedlist><listitem>loose text</listitem></itemizedlist>")
    assert changed
    assert "<para>loose text</para>" in out


def test_inline_bold_italic_become_emphasis():
    out, _, _ = _norm("<ul><li>see <b>this</b> and <i>that</i></li></ul>")
    assert '<emphasis role="strong">this</emphasis>' in out
    assert "<emphasis>that</emphasis>" in out


def test_nested_list_moves_inside_the_listitem_after_the_para():
    out, _, _ = _norm("<ol><li>outer<ul><li>inner</li></ul></li></ol>")
    # itemizedlist sits inside the listitem, after its para
    assert re.search(r"<para>outer</para>\s*<itemizedlist>", out)
    assert validate_fragment(out)[0]


def test_sibling_nested_list_folds_into_previous_item():
    out, _, _ = _norm("<ul><li>a</li><ul><li>a1</li></ul><li>b</li></ul>")
    assert re.search(r"<para>a</para>\s*<itemizedlist>", out)
    assert out.count("<listitem>") == 3  # a, a1, b


def test_html_table_thead_td_cells_become_th_para():
    out, changed, _ = _norm(
        "<table><thead><tr><td>H1</td><td>H2</td></tr></thead>"
        "<tbody><tr><td>a</td><td>b</td></tr></tbody></table>"
    )
    assert changed
    assert out.startswith('<informaltable frame="box" rules="all">')
    assert "<thead>" in out
    assert out.count("<th>") == 2
    assert re.search(r"<th>\s*<para>H1</para>\s*</th>", out)
    assert validate_fragment(out)[0]


def test_leading_all_th_row_is_promoted_to_thead():
    out, _, _ = _norm("<table><tr><th>Name</th><th>Qty</th></tr><tr><td>Bolt</td><td>4</td></tr></table>")
    assert "<thead>" in out and out.count("<th>") == 2
    assert re.search(r"<td>\s*<para>Bolt</para>\s*</td>", out)


def test_headerless_table_has_no_thead():
    out, _, _ = _norm("<table><tbody><tr><td>x</td><td>y</td></tr><tr><td>z</td><td>w</td></tr></tbody></table>")
    assert "<thead>" not in out
    assert out.count("<tr>") == 2


def test_cals_table_converts_to_html_model():
    out, changed, _ = _norm(
        "<informaltable><tgroup cols='2'>"
        "<thead><row><entry>A</entry><entry>B</entry></row></thead>"
        "<tbody><row><entry>1</entry><entry>2</entry></row></tbody></tgroup></informaltable>"
    )
    assert changed
    assert "<tgroup" not in out and "<entry>" not in out and "<row>" not in out
    assert "<th>" in out and "<td>" in out
    assert validate_fragment(out)[0]


def test_colspan_is_kept():
    out, _, _ = _norm("<table><tr><td>x</td><td colspan='2'>wide</td></tr></table>")
    assert 'colspan="2"' in out
    assert validate_fragment(out)[0]


def test_cals_spans_bail_and_return_original_untouched():
    src = "<table><tgroup cols='2'><tbody><row><entry namest='c1' nameend='c2'>wide</entry></row></tbody></tgroup></table>"
    out, changed, diag = _norm(src)
    assert changed is False
    assert out == src
    assert "by hand" in diag


def test_list_item_containing_a_table_bails():
    src = "<ul><li>see <table><tr><td>x</td></tr></table></li></ul>"
    out, changed, diag = _norm(src)
    assert changed is False and out == src
    assert "restructure" in diag


def test_xmlns_is_stripped():
    out, _, _ = _norm('<itemizedlist xmlns="http://docbook.org/ns/docbook"><listitem><para>x</para></listitem></itemizedlist>')
    assert "xmlns" not in out


def test_code_fence_and_prolog_are_stripped():
    out, changed, _ = _norm("```xml\n<?xml version='1.0'?>\n<ul><li>fenced</li></ul>\n```")
    assert changed
    assert out.startswith("<itemizedlist>")
    assert "```" not in out and "<?xml" not in out


def test_ai_wrapper_element_is_unwrapped():
    out, _, _ = _norm("<article><section><ol><li>deep</li></ol></section></article>")
    assert out.startswith("<orderedlist>")


def test_already_correct_input_is_reported_as_no_change():
    good = "<orderedlist>\n  <listitem>\n    <para>step one</para>\n  </listitem>\n</orderedlist>"
    out, changed, diag = _norm(good)
    assert changed is False
    assert "Already" in diag
    # same structure, only whitespace may differ
    assert re.sub(r">\s+<", "><", out) == re.sub(r">\s+<", "><", good)


def test_no_list_or_table_is_left_alone():
    out, changed, diag = _norm("<para>just prose</para>")
    assert changed is False and out == "<para>just prose</para>"
    assert "No list or table" in diag


def test_unparseable_bails_with_original():
    out, changed, diag = _norm("<<< not xml at all >>>")
    assert changed is False and out == "<<< not xml at all >>>"
    assert diag


def test_output_matches_docbook_builders_byte_for_byte():
    # the golden reference: paligo output must equal what wrap_list produces
    from app.docbook import wrap_list, _serialize, _para_element
    from lxml import etree
    li = etree.Element("listitem")
    li.append(_para_element([("one", False, False)]))
    ref = wrap_list("itemizedlist", [_serialize(li)])
    out, _, _ = _norm("<ul><li>one</li></ul>")
    assert out == ref


# --- route ---

def test_fix_xml_page_renders(client):
    r = client.get("/normalize")
    assert r.status_code == 200
    assert b"Fix XML for Paligo" in r.data


def test_fix_xml_post_returns_normalized(client):
    r = client.post("/normalize", data={"xml": "<ul><li>a</li></ul>"})
    assert r.status_code == 200
    body = r.data.decode()
    assert "&lt;itemizedlist&gt;" in body
    assert "Normalized 1 list." in body


def test_fix_xml_card_on_index(client):
    body = client.get("/").data.decode()
    assert ">Fix XML<" in body and "/normalize" in body
