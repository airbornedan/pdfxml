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
