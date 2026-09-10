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
        "Add an empty <para> to fill in",
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
