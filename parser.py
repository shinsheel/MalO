"""Parse MalO tokens into AST (Hy-like s-expressions)."""
from typing import Iterator, List

from malo_ast import ListForm, MalOForm, Number, Str, Symbol
from tokenizer import Token


def _parse_number(value: str) -> Number:
    if "." in value or "e" in value.lower():
        return Number(float(value))
    return Number(int(value))


def parse(tokens: List[Token]) -> MalOForm:
    """Parse a list of tokens into a single top-level form (or raise)."""
    it = iter(tokens)
    token = next(it, None)
    if token is None:
        raise SyntaxError("Unexpected end of input")

    def parse_form(tok: Token) -> MalOForm:
        if tok.kind == "lparen":
            elements: List[MalOForm] = []
            while True:
                nxt = next(it, None)
                if nxt is None:
                    raise SyntaxError(f"Unclosed parenthesis at line {tok.line}")
                if nxt.kind == "rparen":
                    return ListForm(elements)
                elements.append(parse_form(nxt))
        if tok.kind == "lbracket":
            elements = []
            while True:
                nxt = next(it, None)
                if nxt is None:
                    raise SyntaxError(f"Unclosed bracket at line {tok.line}")
                if nxt.kind == "rbracket":
                    return ListForm(elements)
                elements.append(parse_form(nxt))
        if tok.kind == "number":
            return _parse_number(tok.value)
        if tok.kind == "string":
            return Str(tok.value)
        if tok.kind == "symbol":
            return Symbol(tok.value)
        raise SyntaxError(f"Unexpected token {tok.kind!r} at line {tok.line}")

    form = parse_form(token)
    if next(it, None) is not None:
        raise SyntaxError("Multiple top-level forms not supported (use a single s-expr or wrap in do)")
    return form


def parse_all(tokens: List[Token]) -> List[MalOForm]:
    """Parse all tokens into a list of top-level forms (e.g. for (do ...) or multiple exprs)."""
    it = iter(tokens)
    forms: List[MalOForm] = []

    def parse_form(tok: Token) -> MalOForm:
        if tok.kind == "lparen":
            elements = []
            while True:
                nxt = next(it, None)
                if nxt is None:
                    raise SyntaxError(f"Unclosed parenthesis at line {tok.line}")
                if nxt.kind == "rparen":
                    return ListForm(elements)
                elements.append(parse_form(nxt))
        if tok.kind == "lbracket":
            elements = []
            while True:
                nxt = next(it, None)
                if nxt is None:
                    raise SyntaxError(f"Unclosed bracket at line {tok.line}")
                if nxt.kind == "rbracket":
                    return ListForm(elements)
                elements.append(parse_form(nxt))
        if tok.kind == "number":
            return _parse_number(tok.value)
        if tok.kind == "string":
            return Str(tok.value)
        if tok.kind == "symbol":
            return Symbol(tok.value)
        raise SyntaxError(f"Unexpected token {tok.kind!r} at line {tok.line}")

    while True:
        tok = next(it, None)
        if tok is None:
            break
        forms.append(parse_form(tok))
    return forms
