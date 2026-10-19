import pytest

from api.sql.doc import concat, group, hardline, join, line, nest, render, softline

ITEMS = group("SELECT", nest(2, line, join(concat(",", line), ["a", "b", "c"])))


@pytest.mark.parametrize(
    ("width", "expected"),
    [(80, "SELECT a, b, c"), (14, "SELECT a, b, c"), (13, "SELECT\n  a,\n  b,\n  c")],
)
def test_group_breaks_only_when_it_does_not_fit(width, expected):
    assert render(ITEMS, width) == expected


def test_trailing_text_counts_toward_fit():
    # The group fits alone, but not with the text that follows it on the same line
    doc = concat(ITEMS, " FROM t")
    assert render(doc, 21) == "SELECT a, b, c FROM t"
    assert render(doc, 20) == "SELECT\n  a,\n  b,\n  c FROM t"


def test_softline_is_empty_when_flat():
    doc = group("f(", nest(2, softline, "x"), softline, ")")
    assert render(doc, 80) == "f(x)"
    assert render(doc, 3) == "f(\n  x\n)"


def test_hard_line_forces_enclosing_group_to_break():
    doc = group("a", line, group("b", hardline, "c"))
    assert render(doc, 80) == "a\nb\nc"


def test_inner_group_decides_independently():
    inner = group("(", nest(2, softline, "x, y"), softline, ")")
    doc = group("SELECT", nest(2, line, inner, ",", line, "zzzzzzzzzz"))
    assert render(doc, 15) == "SELECT\n  (x, y),\n  zzzzzzzzzz"


def test_nested_indentation_accumulates():
    doc = group("a", nest(2, line, "b", nest(2, line, "c")))
    assert render(doc, 1) == "a\n  b\n    c"
