"""Structural checks for Paligo's pseudo-DocBook / LML (app/lml.py)."""
from app.lml import (
    build_lines,
    check_sections,
    check_tags,
    summarize,
)


def test_balanced_input_flags_nothing():
    assert check_tags("<para>hello</para>") == []


def test_unclosed_opener_is_flagged():
    findings = check_tags("<para>hello")
    assert len(findings) == 1
    assert findings[0]["tag"] == "para"
    assert findings[0]["line"] == 1
    assert "never closed" in findings[0]["message"]


def test_extra_closing_tag_is_flagged():
    findings = check_tags("<para>x</para></para>")
    # the first </para> matched; the second is the orphan
    assert len(findings) == 1
    assert "no matching <para>" in findings[0]["message"]


def test_only_the_unmatched_tag_of_a_pair_type_is_flagged():
    src = "<section><title>T</title><para>a<para>b</para></section>"
    findings = check_tags(src)
    assert len(findings) == 1
    assert findings[0]["tag"] == "para"
    assert "never closed" in findings[0]["message"]


def test_unknown_tags_are_ignored():
    assert check_tags("<foo>x<bar>") == []


def test_self_closing_tag_balances_itself():
    assert check_tags("<mediaobject/>") == []


def test_attributes_and_case_do_not_break_matching():
    assert check_tags('<Para><emphasis role="bold">hi</emphasis></para>') == []


def test_counts_multiple_orphans():
    # </listitem> closes the listitem; both <para> stay open
    findings = check_tags("<listitem><para>one<para>two</listitem>")
    assert len(findings) == 2
    assert [f["tag"] for f in findings] == ["para", "para"]


# --- report assembly -------------------------------------------------
def test_summarize_counts_by_category():
    findings = [
        {"line": 1, "message": "<para> is never closed -- add a </para>."},
        {"line": 3, "message": "<para> sits directly inside a list; move it into a <listitem>."},
        {"line": 3, "message": "<para> sits directly inside a list; move it into a <listitem>."},
    ]
    text = summarize(findings)
    assert text.startswith("3 problems:")
    assert "1 unclosed tag" in text
    assert "2 misplaced elements" in text


def test_summarize_clean():
    assert summarize([]) == "No problems found."


def test_build_lines_wraps_offending_tag_and_attaches_note():
    src = "<orderedlist>\n<para>x</para>\n</orderedlist>"
    findings = [{"line": 2, "tag": "para",
                 "message": "move it into a <listitem>."}]
    lines = build_lines(src, findings)
    assert len(lines) == 3
    assert '<span class="lml-bad">&lt;para&gt;</span>' in lines[1]["html"]
    assert lines[1]["notes"] == [{"message": "move it into a <listitem>.", "fixes": []}]
    assert lines[0]["notes"] == [] and lines[2]["notes"] == []


def test_build_lines_escapes_text():
    lines = build_lines("<para>a &amp; b</para>", [])
    assert "&amp;amp;" in lines[0]["html"]
    assert "<span" not in lines[0]["html"]


from app.lml import strip_xinfo_attrs


def test_xinfo_attrs_are_stripped_everywhere_but_the_first_section():
    src = (
        '<section xmlns="http://docbook.org/ns/docbook" '
        'xmlns:xinfo="http://ns.expertinfo.se/cms/xmlns/1.0" '
        'xinfo:resource="UUID-1" xinfo:resource-id="188372">'
        '<title>test</title>'
        '<orderedlist><listitem><para xinfo:text="188409">one</para></listitem></orderedlist>'
        '<section xinfo:resource="UUID-2"><title>nested</title></section>'
        '</section>'
    )
    out = strip_xinfo_attrs(src)
    assert 'xinfo:resource="UUID-1"' in out
    assert 'xinfo:resource-id="188372"' in out
    assert 'xinfo:text="188409"' not in out
    assert 'xinfo:resource="UUID-2"' not in out


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


def test_stray_content_in_row_is_reported():
    src = (
        "<informaltable><tbody>"
        "<tr><para>oops</para><td>1</td></tr>"
        "<tr><td>2</td><para>still oops</para></tr>"
        "</tbody></informaltable>"
    )
    msgs = " ".join(f["message"] for f in check_tables(src))
    assert msgs.count("sits directly inside <tr>; it must be inside a <td> or <th>") == 2


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


def test_imageobject_outside_mediaobject_is_reported():
    src = "<itemizedlist><listitem><imageobject/></listitem></itemizedlist>"
    msgs = " ".join(f["message"] for f in check_lists(src))
    assert "inside a <mediaobject>" in msgs


def test_imageobject_outside_mediaobject_is_reported_globally():
    from app.lml import check_mediaobjects
    src = "<section><imageobject/></section>"
    msgs = " ".join(f["message"] for f in check_mediaobjects(src))
    assert "inside a <mediaobject>" in msgs


def test_content_after_nested_section_is_reported():
    src = (
        "<section><title>T</title>"
        "<para>before</para>"
        "<section><title>S</title><para>sub</para></section>"
        "<informaltable><tbody><tr><td>later</td></tr></tbody></informaltable>"
        "</section>"
    )
    findings = check_sections(src)
    assert len(findings) == 1
    assert findings[0]["tag"] == "informaltable"
    assert "after a nested <section>" in findings[0]["message"]


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


def test_text_between_thead_and_tr_is_reported():
    src = "<informaltable><thead>stray<tr><th>H</th></tr></thead><tbody><tr><td>1</td></tr></tbody></informaltable>"
    msgs = " ".join(f["message"] for f in check_tables(src))
    assert "directly inside <thead>; it must be inside a <tr>" in msgs


def test_tag_between_tbody_and_tr_is_reported():
    src = "<informaltable><tbody><note/><tr><td>1</td></tr></tbody></informaltable>"
    msgs = " ".join(f["message"] for f in check_tables(src))
    assert "directly inside <tbody>; it must be inside a <tr>" in msgs


def test_text_between_cells_is_reported():
    src = "<informaltable><tbody><tr><td>1</td> stray <td>2</td></tr></tbody></informaltable>"
    msgs = " ".join(f["message"] for f in check_tables(src))
    assert "directly inside <tr>; it must be inside a <td> or <th>" in msgs


def test_content_after_last_cell_before_row_close_is_reported():
    src = "<informaltable><tbody><tr><td>1</td>stray</tr></tbody></informaltable>"
    msgs = " ".join(f["message"] for f in check_tables(src))
    assert "directly inside <tr>; it must be inside a <td> or <th>" in msgs


def test_formal_table_with_caption_is_recognized_and_clean():
    src = (
        "<table frame=\"box\" rules=\"all\">"
        "<caption>Parts</caption>"
        "<thead><tr><th>Part</th></tr></thead>"
        "<tbody><tr><td><para>1</para></td></tr></tbody>"
        "</table>"
    )
    assert check_tables(src) == []


def test_missing_table_close_names_the_right_tag():
    msgs = " ".join(f["message"] for f in check_tables("<table><tbody><tr><td>1</td></tr></tbody>"))
    assert "no </table>" in msgs


# --- content outside the root <section> -------------------------------
def test_prolog_before_root_is_not_flagged():
    src = '<?xml version="1.0"?><section><title>x</title><para>y</para></section>'
    assert check_sections(src) == []


def test_tag_before_root_is_flagged():
    src = "<para>stray</para><section><title>x</title><para>y</para></section>"
    msgs = " ".join(f["message"] for f in check_sections(src))
    assert "before the topic's <section> root" in msgs


def test_tag_after_root_is_flagged():
    src = "<section><title>x</title><para>y</para></section><para>stray</para>"
    msgs = " ".join(f["message"] for f in check_sections(src))
    assert "after the topic's <section> root closes" in msgs


def test_bare_text_trailing_after_root_is_flagged():
    src = "<section><title>x</title><para>y</para></section>stray bare text"
    msgs = " ".join(f["message"] for f in check_sections(src))
    assert "after the topic's <section> root closes" in msgs


def test_second_top_level_section_is_flagged():
    src = ("<section><title>x</title><para>y</para></section>"
           "<section><title>z</title><para>w</para></section>")
    msgs = " ".join(f["message"] for f in check_sections(src))
    assert "after the topic's <section> root closes" in msgs


def test_outside_root_is_reported_once_per_side():
    src = "<section><title>x</title></section><para>a</para><para>b</para>"
    findings = check_sections(src)
    assert len(findings) == 1


def test_well_formed_single_topic_is_clean():
    src = "<section><title>x</title><para>y</para></section>"
    assert check_sections(src) == []
