"""A small Wadler-style layout tree and a renderer that fits it to a line width."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


@dataclass(frozen=True, slots=True)
class Text:
    s: str


@dataclass(frozen=True, slots=True)
class Line:
    """A line break; rendered as `flat` when its enclosing group fits on one line."""

    hard: bool = False  # always breaks, and forces enclosing groups to break
    flat: str = " "


@dataclass(frozen=True, slots=True)
class Nest:
    indent: int
    doc: Doc


@dataclass(frozen=True, slots=True)
class Group:
    """Rendered flat if it fits in the remaining width, otherwise with every Line broken."""

    doc: Doc


@dataclass(frozen=True, slots=True)
class Concat:
    parts: tuple[Doc, ...]


Doc = Text | Line | Nest | Group | Concat

line = Line()
softline = Line(flat="")
hardline = Line(hard=True)


def text(s: str) -> Text:
    return Text(s)


def concat(*docs: Doc | str) -> Concat:
    return Concat(tuple(Text(d) if isinstance(d, str) else d for d in docs))


def join(sep: Doc | str, docs: list[Doc]) -> Concat:
    parts: list[Doc | str] = []
    for i, doc in enumerate(docs):
        if i:
            parts.append(sep)
        parts.append(doc)
    return concat(*parts)


def nest(indent: int, *docs: Doc | str) -> Nest:
    return Nest(indent, concat(*docs))


def group(*docs: Doc | str) -> Group:
    return Group(concat(*docs))


class _Mode(Enum):
    FLAT = auto()
    BREAK = auto()


_Item = tuple[int, _Mode, Doc]


def render(doc: Doc, width: int = 80) -> str:
    out: list[str] = []
    col = 0
    stack: list[_Item] = [(0, _Mode.BREAK, doc)]
    while stack:
        indent, mode, d = stack.pop()
        match d:
            case Text(s):
                out.append(s)
                col += len(s)
            case Line(hard, flat) if mode is _Mode.FLAT and not hard:
                out.append(flat)
                col += len(flat)
            case Line():
                out.append("\n" + " " * indent)
                col = indent
            case Nest(n, inner):
                stack.append((indent + n, mode, inner))
            case Concat(parts):
                stack.extend((indent, mode, p) for p in reversed(parts))
            case Group(inner):
                flat = mode is _Mode.FLAT or _fits(
                    width - col, (indent, _Mode.FLAT, inner), stack
                )
                stack.append((indent, _Mode.FLAT if flat else _Mode.BREAK, inner))
    return "".join(out)


def _fits(width: int, item: _Item, rest: list[_Item]) -> bool:
    # Measure `item` flat, then whatever follows it, up to the next line break.
    stack = [item]
    pending = len(rest)
    while width >= 0:
        if not stack:
            if not pending:
                return True
            pending -= 1
            stack.append(rest[pending])
        indent, mode, d = stack.pop()
        match d:
            case Text(s):
                width -= len(s)
            case Line(hard, flat):
                if mode is _Mode.BREAK:
                    return True
                if hard:
                    # Only a group being measured is flat here, and it can't hold a hard line
                    return False
                width -= len(flat)
            case Nest(n, inner):
                stack.append((indent + n, mode, inner))
            case Concat(parts):
                stack.extend((indent, mode, p) for p in reversed(parts))
            case Group(inner):
                stack.append((indent, mode, inner))
    return False
