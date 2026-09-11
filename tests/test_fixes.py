"""Candidate fixes for LML findings (app/fixes.py)."""
import re

from app.fixes import _words, suggest_fixes
from app.lml import check_lists, check_tags


def _finding_with_fix(findings, kind):
    return next(f for f in findings if f.get("fix", {}).get("kind") == kind)


def _words_of(text):
    return _words(text)


# --- loose block in a list -------------------------------------------
_LOOSE = (
    "<orderedlist>\n"
    "  <listitem>\n"
    "    <para>Step one.</para>\n"
    "  </listitem>\n"
    "  <para>This is stray.</para>\n"
    "</orderedlist>"
)


def test_loose_block_offers_three_fixes():
    finding = _finding_with_fix(check_lists(_LOOSE), "loose-block-in-list")
    fixes = suggest_fixes(_LOOSE, finding)
    assert [f["label"] for f in fixes] == [
        "Make it its own list item",
        "Add it to the item above",
        "Move it out below the list",
    ]
    for fix in fixes:
        assert _words(fix["new_text"]) == _words(_LOOSE)   # nothing lost


def test_loose_block_new_item_is_wrapped():
    finding = _finding_with_fix(check_lists(_LOOSE), "loose-block-in-list")
    new_item = suggest_fixes(_LOOSE, finding)[0]["new_text"]
    # the stray para is now inside its own <listitem>
    assert re.search(r"<listitem>\s*<para>This is stray\.</para>\s*</listitem>",
                     new_item)
    # and re-checking finds nothing
    assert check_lists(new_item) == []


def test_loose_block_move_out_leaves_list_clean():
    finding = _finding_with_fix(check_lists(_LOOSE), "loose-block-in-list")
    moved = suggest_fixes(_LOOSE, finding)[2]["new_text"]
    assert moved.index("This is stray") > moved.index("</orderedlist>")
    assert check_lists(moved) == []


# --- stray closing tag ---------------------------------------------------
def test_stray_close_delete():
    src = "<para>x</para></para>"
    finding = _finding_with_fix(check_tags(src), "delete-stray-close")
    fixes = suggest_fixes(src, finding)
    assert len(fixes) == 1
    assert fixes[0]["new_text"] == "<para>x</para>"
    assert check_tags(fixes[0]["new_text"]) == []


# --- empty list item ---------------------------------------------------
_EMPTY = "<itemizedlist>\n  <listitem></listitem>\n</itemizedlist>"


def test_empty_listitem_two_fixes():
    finding = _finding_with_fix(check_lists(_EMPTY), "empty-listitem")
    fixes = suggest_fixes(_EMPTY, finding)
    assert [f["label"] for f in fixes] == [
        "Add an empty paragraph",
        "Delete the empty list item",
    ]
    add_para = fixes[0]["new_text"]
    assert "<para></para>" in add_para
    delete = fixes[1]["new_text"]
    assert "<listitem>" not in delete
    # deleting an empty item leaves an empty list -> still flagged, but no crash
    assert isinstance(check_lists(delete), list)


# --- bare text directly in a list ------------------------------------
def test_bare_text_wrapped():
    src = "<orderedlist>\n  stray words\n  <listitem><para>ok</para></listitem>\n</orderedlist>"
    finding = _finding_with_fix(check_lists(src), "bare-text-in-list")
    fixes = suggest_fixes(src, finding)
    assert len(fixes) == 1
    new_text = fixes[0]["new_text"]
    assert "<listitem><para>stray words</para></listitem>" in new_text
    assert _words(new_text) == _words(src)
    assert check_lists(new_text) == []


# --- the guarantee ---------------------------------------------------
def test_guard_rejects_content_loss():
    # a builder that dropped a word would be filtered out
    from app import fixes as fx

    src = "<listitem>keep this</listitem>"
    assert not fx._guard(src, "<listitem>keep</listitem>")   # 'this' lost
    assert fx._guard(src, "<listitem><para>keep this</para></listitem>")


# --- content after a subsection -------------------------------------
from app.lml import check_sections

_AFTER_SUB = (
    "<section>\n"
    "  <title>Parent</title>\n"
    "  <para>Intro.</para>\n"
    "  <section>\n"
    "    <title>First sub</title>\n"
    "    <para>Sub body.</para>\n"
    "  </section>\n"
    "  <para>This got pasted too low.</para>\n"
    "</section>"
)


def test_content_after_subsection_three_fixes():
    from app import fixes as fx

    finding = _finding_with_fix(check_sections(_AFTER_SUB), "content-after-subsection")
    fixes = suggest_fixes(_AFTER_SUB, finding)
    assert [f["label"] for f in fixes] == [
        "Move it into the previous subsection",
        "Move it above the subsections",
        "Put it in a new subsection",
    ]
    for fix in fixes:
        assert fx._guard(_AFTER_SUB, fix["new_text"])   # no input word lost


def test_move_above_subsections_reclears():
    finding = _finding_with_fix(check_sections(_AFTER_SUB), "content-after-subsection")
    fixes = suggest_fixes(_AFTER_SUB, finding)
    above = next(f for f in fixes if f["label"] == "Move it above the subsections")
    new = above["new_text"]
    assert new.index("pasted too low") < new.index("<title>First sub")
    assert check_sections(new) == []


def test_into_previous_subsection_reclears():
    finding = _finding_with_fix(check_sections(_AFTER_SUB), "content-after-subsection")
    fixes = suggest_fixes(_AFTER_SUB, finding)
    into = next(f for f in fixes if f["label"] == "Move it into the previous subsection")
    new = into["new_text"]
    assert new.index("Sub body") < new.index("pasted too low") < new.index("</section>\n</section>")
    assert check_sections(new) == []


def test_wrap_in_new_subsection_is_valid_with_placeholder_title():
    finding = _finding_with_fix(check_sections(_AFTER_SUB), "content-after-subsection")
    fixes = suggest_fixes(_AFTER_SUB, finding)
    wrap = fixes[-1]["new_text"]
    assert "<title>Untitled section</title>" in wrap
    assert check_sections(wrap) == []   # structurally clean; title is the to-do


# --- unclosed <para> -----------------------------------------------------
def test_unclosed_para_close_before_next_block():
    src = "<listitem>\n  <para>Mount the ECU.\n</listitem>"
    finding = _finding_with_fix(check_tags(src), "insert-close")
    fixes = suggest_fixes(src, finding)
    assert len(fixes) == 1
    new = fixes[0]["new_text"]
    assert new == "<listitem>\n  <para>Mount the ECU.</para>\n</listitem>"
    assert check_tags(new) == []


def test_unclosed_para_before_sibling_para():
    src = "<td><para>First\n<para>Second.</para></td>"
    finding = _finding_with_fix(check_tags(src), "insert-close")
    fixes = suggest_fixes(src, finding)
    assert len(fixes) == 1                       # not a duplicate (text between)
    new = fixes[0]["new_text"]
    assert new == "<td><para>First</para>\n<para>Second.</para></td>"
    assert check_tags(new) == []


def test_duplicate_para_opener_offers_delete():
    src = "<listitem><para><para>Only text.</para></listitem>"
    finding = _finding_with_fix(check_tags(src), "insert-close")
    labels = [f["label"] for f in suggest_fixes(src, finding)]
    assert labels == ["Delete the extra opening tag", "Close the paragraph here"]
    delete = suggest_fixes(src, finding)[0]["new_text"]
    assert delete == "<listitem><para>Only text.</para></listitem>"
    assert check_tags(delete) == []


# --- imageobject outside a mediaobject ------------------------------
from app.lml import check_mediaobjects


def test_wrap_imageobject_in_mediaobject():
    src = (
        "<section>\n"
        "  <title>x</title>\n"
        "  <imageobject>\n"
        '    <imagedata fileref="UUID-abc"/>\n'
        "  </imageobject>\n"
        "</section>"
    )
    finding = _finding_with_fix(check_mediaobjects(src), "wrap-in-mediaobject")
    fixes = suggest_fixes(src, finding)
    assert [f["label"] for f in fixes] == ["Wrap it in a mediaobject"]
    new = fixes[0]["new_text"]
    assert "<mediaobject>" in new and "</mediaobject>" in new
    assert 'fileref="UUID-abc"' in new
    assert _words(new) == _words(src)                 # nothing lost
    assert check_mediaobjects(new) == []              # cascades clean
