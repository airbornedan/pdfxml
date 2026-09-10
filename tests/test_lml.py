"""Tag-balance check for Paligo's pseudo-DocBook (app/lml.py)."""
from app.lml import check_tags


def test_balanced_input_flags_nothing():
    html, n = check_tags("<para>hello</para>")
    assert n == 0
    assert "lml-bad" not in html
    assert html == "&lt;para&gt;hello&lt;/para&gt;"


def test_unclosed_opener_is_flagged():
    html, n = check_tags("<para>hello")
    assert n == 1
    assert '<span class="lml-bad">&lt;para&gt;</span>hello' == html


def test_extra_closing_tag_is_flagged():
    html, n = check_tags("<para>x</para></para>")
    assert n == 1
    # the first </para> matched; the second is the orphan
    assert html.count("lml-bad") == 1
    assert html.endswith('<span class="lml-bad">&lt;/para&gt;</span>')


def test_only_the_unmatched_tag_of_a_pair_type_is_flagged():
    src = "<section><title>T</title><para>a<para>b</para></section>"
    html, n = check_tags(src)
    assert n == 1
    # section + title + the inner para all close; the first <para> does not
    assert html.count("lml-bad") == 1
    assert '<span class="lml-bad">&lt;para&gt;</span>a' in html


def test_unknown_tags_are_ignored():
    html, n = check_tags("<foo>x<bar>")
    assert n == 0
    assert "lml-bad" not in html


def test_self_closing_tag_balances_itself():
    html, n = check_tags("<mediaobject/>")
    assert n == 0
    assert "lml-bad" not in html


def test_attributes_and_case_do_not_break_matching():
    html, n = check_tags('<Para><emphasis role="bold">hi</emphasis></para>')
    assert n == 0
    assert "lml-bad" not in html


def test_text_is_html_escaped():
    html, _ = check_tags("<para>a &amp; b &lt; c</para>")
    assert "&amp;amp;" in html and "&amp;lt;" in html
    assert "<span" not in html  # nothing flagged, so no markup added


def test_counts_multiple_orphans_across_elements():
    html, n = check_tags("<listitem><para>one<para>two</listitem>")
    # listitem never closes, and one <para> is left open
    assert n == 2
    assert html.count("lml-bad") == 2


# --- check_tables --------------------------------------------------------
from app.lml import check_tables

_GOOD = (
    "<informaltable frame=\"box\" rules=\"all\">\n"
    "  <thead><tr><th>A</th><th>B</th></tr></thead>\n"
    "  <tbody>\n"
    "    <tr><td>1</td><td>2</td></tr>\n"
    "    <tr><td>3</td><td>4</td></tr>\n"
    "  </tbody>\n"
    "</informaltable>"
)


def test_well_formed_table_has_no_findings():
    assert check_tables(_GOOD) == []


def test_no_findings_when_there_is_no_table():
    assert check_tables("<para>just text</para>") == []


def test_missing_table_close_is_reported():
    src = "<informaltable><tbody><tr><td>1</td></tr></tbody>"
    msgs = " ".join(f["message"] for f in check_tables(src))
    assert "no </informaltable>" in msgs


def test_table_with_no_rows_is_reported():
    msgs = " ".join(f["message"] for f in check_tables("<informaltable></informaltable>"))
    assert "no rows" in msgs


def test_row_with_no_cells_is_reported():
    src = "<informaltable><tbody><tr></tr></tbody></informaltable>"
    msgs = " ".join(f["message"] for f in check_tables(src))
    assert "no cells" in msgs


def test_ragged_column_counts_are_reported():
    src = (
        "<informaltable><tbody>\n"
        "<tr><td>1</td><td>2</td></tr>\n"
        "<tr><td>3</td><td>4</td><td>5</td></tr>\n"
        "</tbody></informaltable>"
    )
    msgs = " ".join(f["message"] for f in check_tables(src))
    assert "different column counts" in msgs


def test_unclosed_tr_is_reported():
    src = "<informaltable><tbody><tr><td>1</td><td>2</td><tr><td>3</td><td>4</td></tr></tbody></informaltable>"
    msgs = " ".join(f["message"] for f in check_tables(src))
    assert "has no </tr>" in msgs


def test_doubled_cell_close_is_reported():
    src = "<informaltable><tbody><tr><td>1</td></td><td>2</td></tr></informaltable>"
    msgs = " ".join(f["message"] for f in check_tables(src))
    assert "no matching open cell" in msgs


def test_cell_closed_by_wrong_tag_is_reported():
    src = "<informaltable><thead><tr><th>A</td><th>B</th></tr></thead></informaltable>"
    msgs = " ".join(f["message"] for f in check_tables(src))
    assert "closes a <th> cell" in msgs


def test_finding_carries_a_line_number():
    src = "<informaltable><tbody>\n<tr><td>1</td></tr>\n<tr><td>2</td><td>3</td></tr>\n</tbody></informaltable>"
    findings = check_tables(src)
    assert findings and all(isinstance(f["line"], int) for f in findings)


# --- check_lists -------------------------------------------------------
from app.lml import check_lists


def test_well_formed_list_has_no_findings():
    src = ("<orderedlist>"
           "<listitem><para>one</para></listitem>"
           "<listitem><para>two</para></listitem>"
           "</orderedlist>")
    assert check_lists(src) == []


def test_no_findings_without_a_list():
    assert check_lists("<para>text</para>") == []


def test_loose_para_directly_in_list_is_reported():
    src = ("<orderedlist>"
           "<para>Step one</para>"
           "<listitem><para>Step two</para></listitem>"
           "</orderedlist>")
    msgs = " ".join(f["message"] for f in check_lists(src))
    assert "directly inside a list" in msgs


def test_loose_text_between_items_is_reported():
    src = ("<itemizedlist><listitem><para>a</para></listitem>"
           " and also "
           "<listitem><para>b</para></listitem></itemizedlist>")
    msgs = " ".join(f["message"] for f in check_lists(src))
    assert "Text sits directly inside a list" in msgs


def test_empty_listitem_is_reported():
    src = "<orderedlist><listitem></listitem></orderedlist>"
    msgs = " ".join(f["message"] for f in check_lists(src))
    assert "has no content" in msgs


def test_listitem_with_only_bare_text_is_reported():
    src = "<orderedlist><listitem>just words</listitem></orderedlist>"
    msgs = " ".join(f["message"] for f in check_lists(src))
    assert "has no content" in msgs


def test_listitem_with_only_a_mediaobject_is_ok():
    src = ("<itemizedlist><listitem>"
           "<mediaobject><imageobject/></mediaobject>"
           "</listitem></itemizedlist>")
    assert check_lists(src) == []


def test_listitem_with_only_a_sublist_is_ok():
    src = ("<orderedlist><listitem>"
           "<itemizedlist><listitem><para>x</para></listitem></itemizedlist>"
           "</listitem></orderedlist>")
    assert check_lists(src) == []


def test_dangling_listitem_is_reported():
    src = ("<orderedlist>"
           "<listitem><para>a</para>"
           "<listitem><para>b</para></listitem>"
           "</orderedlist>")
    msgs = " ".join(f["message"] for f in check_lists(src))
    assert "has no </listitem>" in msgs


def test_stray_closing_listitem_is_reported():
    src = "<orderedlist><listitem><para>a</para></listitem></listitem></orderedlist>"
    msgs = " ".join(f["message"] for f in check_lists(src))
    assert "no matching <listitem>" in msgs


def test_unclosed_list_is_reported():
    src = "<orderedlist><listitem><para>a</para></listitem>"
    msgs = " ".join(f["message"] for f in check_lists(src))
    assert "has no closing tag" in msgs


def test_list_with_no_items_is_reported():
    msgs = " ".join(f["message"] for f in check_lists("<itemizedlist></itemizedlist>"))
    assert "has no <listitem> elements" in msgs
