"""AST for MalO (Hy-like s-expressions)."""
from dataclasses import dataclass
from typing import Dict, List, Union


@dataclass
class Symbol:
    """Symbol (identifier)."""
    name: str

    def __repr__(self) -> str:
        return f"Symbol({self.name!r})"


@dataclass
class Number:
    """Numeric literal."""
    value: Union[int, float]

    def __repr__(self) -> str:
        return f"Number({self.value})"


@dataclass
class Str:
    """String literal."""
    value: str

    def __repr__(self) -> str:
        return f"Str({self.value!r})"


@dataclass
class ListForm:
    """S-expression: (form ...)."""
    elements: List["MalOForm"]

    def __repr__(self) -> str:
        return f"ListForm({self.elements})"


@dataclass
class DictForm:
    """Dict literal: {key val ...}."""
    elements: List["MalOForm"]

    def __repr__(self) -> str:
        return f"DictForm({self.elements})"


MalOForm = Union[Symbol, Number, Str, ListForm, DictForm]


def clone_and_substitute(form: "MalOForm", subs: Dict[str, "MalOForm"]) -> "MalOForm":
    """Return a copy of form with symbols in subs replaced by their values."""
    if isinstance(form, Symbol):
        return subs.get(form.name, form)
    if isinstance(form, Number):
        return Number(form.value)
    if isinstance(form, Str):
        return Str(form.value)
    if isinstance(form, ListForm):
        return ListForm([clone_and_substitute(e, subs) for e in form.elements])
    if isinstance(form, DictForm):
        return DictForm([clone_and_substitute(e, subs) for e in form.elements])
    return form
