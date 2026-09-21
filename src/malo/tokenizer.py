import re
from dataclasses import dataclass
from typing import Iterator, List


@dataclass
class Token:
    kind: str
    value: str
    line: int
    col: int


def _count_leading_tabs(line: str) -> int:
    """Return number of leading tab characters."""
    count = 0
    for c in line:
        if c == "\t":
            count += 1
        else:
            break
    return count


def tokenize_with_indent(source: str) -> Iterator[Token]:
    """
    Tokenize with virtual brackets from tab indentation.
    Block structure is indentation, not wrapping parentheses:
    - Each line with text implies "(" at the start (unless the line already starts with
      "(" or a reader-macro prefix ` ~ ~@).
    - When indent drops (fewer tabs on next line), emit ")" for each dropped level.
    - When indent stays the same and previous line had content, emit ")" to close that line's list.
    Only tab characters count as indent; spaces do not.
    """
    lines = source.split("\n")
    current_indent = 0
    virtual_open_count = 0
    prev_had_virtual_open = False

    for line_no, line in enumerate(lines, 1):
        tab_count = _count_leading_tabs(line)
        content = line[tab_count:]
        line_tokens = list(tokenize(content)) if content.strip() else []

        # Ignore blank/comment-only lines for virtual bracket transitions.
        if not line_tokens:
            continue

        # Emit ")" for dropped indent levels
        if tab_count < current_indent:
            # Close the previous line's form before leaving its indent level
            if prev_had_virtual_open:
                virtual_open_count -= 1
                yield Token("rparen", ")", line_no, 1)
                prev_had_virtual_open = False
            for _ in range(current_indent - tab_count):
                virtual_open_count -= 1
                yield Token("rparen", ")", line_no, 1)

        # Same indent and previous line opened a list: close it
        if tab_count == current_indent and prev_had_virtual_open:
            virtual_open_count -= 1
            yield Token("rparen", ")", line_no, 1)

        prev_had_virtual_open = False

        # Only add virtual "(" if line produces tokens and doesn't start with
        # "(" or a reader-macro prefix (` ~ ~@)
        if line_tokens[0].kind not in (
            "lparen",
            "quasiquote",
            "unquote",
            "unquote_splice",
        ):
            virtual_open_count += 1
            yield Token("lparen", "(", line_no, tab_count + 1)
            prev_had_virtual_open = True
        else:
            prev_had_virtual_open = False
        for t in line_tokens:
            yield Token(t.kind, t.value, line_no, t.col)
        current_indent = tab_count

    # Close any remaining virtual opens at EOF
    for _ in range(virtual_open_count):
        yield Token("rparen", ")", len(lines) + 1, 1)


def tokenize(text: str) -> Iterator[Token]:
    """Split Hylang-like source into tokens (parens, strings, numbers, symbols, comments)."""
    i = 0
    line, col = 1, 1
    n = len(text)

    def peek():
        return text[i] if i < n else ""

    def advance():
        nonlocal i, line, col
        if i < n:
            if text[i] == "\n":
                line += 1
                col = 1
            else:
                col += 1
            i += 1

    def skip_whitespace():
        nonlocal i, line, col
        while i < n and text[i] in " \t\r\n":
            advance()

    while i < n:
        skip_whitespace()
        if i >= n:
            break
        start_line, start_col = line, col
        c = peek()

        if c == ";":
            while i < n and text[i] != "\n":
                advance()
            continue
        if c == "(":
            advance()
            yield Token("lparen", "(", start_line, start_col)
            continue
        if c == ")":
            advance()
            yield Token("rparen", ")", start_line, start_col)
            continue
        if c == "[":
            advance()
            yield Token("lbracket", "[", start_line, start_col)
            continue
        if c == "]":
            advance()
            yield Token("rbracket", "]", start_line, start_col)
            continue
        if c == "{":
            advance()
            yield Token("lbrace", "{", start_line, start_col)
            continue
        if c == "}":
            advance()
            yield Token("rbrace", "}", start_line, start_col)
            continue
        # Reader macros: `form, ~form, ~@form
        if c == "`":
            advance()
            yield Token("quasiquote", "`", start_line, start_col)
            continue
        if c == "~":
            advance()
            if peek() == "@":
                advance()
                yield Token("unquote_splice", "~@", start_line, start_col)
            else:
                yield Token("unquote", "~", start_line, start_col)
            continue
        if c == '"':
            advance()
            value = []
            while i < n and text[i] != '"':
                if text[i] == "\\":
                    advance()
                    if i < n:
                        esc = text[i]
                        value.append({"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}.get(esc, esc))
                        advance()
                else:
                    value.append(text[i])
                    advance()
            if i < n:
                advance()  # closing "
            yield Token("string", "".join(value), start_line, start_col)
            continue
        if c in "-+" and i + 1 < n and text[i + 1].isdigit():
            num_start = i
            advance()
            while i < n and text[i] in "0123456789.":
                advance()
            if i < n and text[i].lower() in "ej":
                advance()
                if i < n and text[i] in "-+":
                    advance()
                while i < n and text[i].isdigit():
                    advance()
            yield Token("number", text[num_start:i], start_line, start_col)
            continue
        if c.isdigit() or (c == "." and i + 1 < n and text[i + 1].isdigit()):
            num_start = i
            while i < n and text[i] in "0123456789.":
                advance()
            if i < n and text[i].lower() in "ej":
                advance()
                if i < n and text[i] in "-+":
                    advance()
                while i < n and text[i].isdigit():
                    advance()
            yield Token("number", text[num_start:i], start_line, start_col)
            continue
        # symbol (identifier or operator)
        sym_start = i
        while i < n:
            c = text[i]
            if c in " \t\r\n();\"[]{}`~":
                break
            if c == ";":
                break
            advance()
        if sym_start < i:
            yield Token("symbol", text[sym_start:i], start_line, start_col)

    return