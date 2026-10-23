"""Parse MalO tokens into AST (Hy-like s-expressions)."""
from typing import List, Optional

from .malo_ast import DictForm, ListForm, MalOForm, Number, Str, Symbol
from .tokenizer import Token

_READER_MACROS = {
    "quasiquote": "quasiquote",
    "unquote": "unquote",
    "unquote_splice": "unquote-splice",
}


class _Tokens:
    """Token iterator with one-token lookahead."""

    def __init__(self, tokens: List[Token]) -> None:
        self._it = iter(tokens)
        self._peek: Optional[Token] = None
        self._has_peek = False

    def peek(self) -> Optional[Token]:
        if not self._has_peek:
            self._peek = next(self._it, None)
            self._has_peek = True
        return self._peek

    def next(self) -> Optional[Token]:
        if self._has_peek:
            self._has_peek = False
            tok = self._peek
            self._peek = None
            return tok
        return next(self._it, None)


def _parse_number(value: str) -> Number:
    if "." in value or "e" in value.lower():
        return Number(float(value))
    return Number(int(value))


def _make_parse_form(stream: _Tokens):
    def parse_primary(tok: Token) -> MalOForm:
        if tok.kind in _READER_MACROS:
            nxt = stream.next()
            if nxt is None:
                raise SyntaxError(
                    f"Reader macro {tok.value!r} missing form at line {tok.line}"
                )
            return ListForm([Symbol(_READER_MACROS[tok.kind]), parse_form(nxt)])
        if tok.kind == "lparen":
            elements: List[MalOForm] = []
            while True:
                nxt = stream.next()
                if nxt is None:
                    raise SyntaxError(f"Unclosed parenthesis at line {tok.line}")
                if nxt.kind == "rparen":
                    return ListForm(elements)
                elements.append(parse_form(nxt))
        if tok.kind in ("lbracket", "lindex"):
            elements = []
            while True:
                nxt = stream.next()
                if nxt is None:
                    raise SyntaxError(f"Unclosed bracket at line {tok.line}")
                if nxt.kind == "rbracket":
                    return ListForm(elements)
                elements.append(parse_form(nxt))
        if tok.kind == "lbrace":
            elements = []
            while True:
                nxt = stream.next()
                if nxt is None:
                    raise SyntaxError(f"Unclosed brace at line {tok.line}")
                if nxt.kind == "rbrace":
                    return DictForm(elements)
                elements.append(parse_form(nxt))
        if tok.kind == "number":
            return _parse_number(tok.value)
        if tok.kind == "string":
            return Str(tok.value)
        if tok.kind == "symbol":
            return Symbol(tok.value)
        raise SyntaxError(f"Unexpected token {tok.kind!r} at line {tok.line}")

    def parse_indexes(form: MalOForm) -> MalOForm:
        """obj[key] is (get obj key). A spaced [list] stays a call."""
        while True:
            nxt = stream.peek()
            if nxt is None or nxt.kind != "lindex":
                return form
            stream.next()
            key_tok = stream.next()
            if key_tok is None:
                raise SyntaxError(f"Unclosed index at line {nxt.line}")
            if key_tok.kind == "rbracket":
                raise SyntaxError(f"Empty index at line {nxt.line}")
            key = parse_form(key_tok)
            end = stream.next()
            if end is None or end.kind != "rbracket":
                raise SyntaxError(f"Index requires one key at line {nxt.line}")
            form = ListForm([Symbol("get"), form, key])

    def parse_form(tok: Token) -> MalOForm:
        return parse_indexes(parse_primary(tok))

    return parse_form


def parse(tokens: List[Token]) -> MalOForm:
    """Parse a list of tokens into a single top-level form (or raise)."""
    stream = _Tokens(tokens)
    token = stream.next()
    if token is None:
        raise SyntaxError("Unexpected end of input")

    parse_form = _make_parse_form(stream)
    form = parse_form(token)
    if stream.next() is not None:
        raise SyntaxError("Multiple top-level forms not supported (use a single s-expr or wrap in do)")
    return form


def parse_all(tokens: List[Token]) -> List[MalOForm]:
    """Parse all tokens into a list of top-level forms (e.g. for (do ...) or multiple exprs)."""
    stream = _Tokens(tokens)
    forms: List[MalOForm] = []
    parse_form = _make_parse_form(stream)

    while True:
        tok = stream.next()
        if tok is None:
            break
        forms.append(parse_form(tok))
    return forms
