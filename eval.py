"""Evaluate MalO AST (Hy-like interpreter)."""
from typing import Any, Callable, Dict, List

from malo_ast import ListForm, MalOForm, Number, Str, Symbol, clone_and_substitute

# Key in env holding macro definitions (name -> (form, env) -> MalOForm)
_MACROS_KEY = "__malo_macros__"


class MalOError(Exception):
    """Raised on MalO runtime/syntax errors."""
    pass


class _BreakSignal(Exception):
    """Internal control-flow signal for break."""
    pass


class _ContinueSignal(Exception):
    """Internal control-flow signal for continue."""
    pass


def _get_macros(env: Dict[str, Any]) -> Dict[str, Any]:
    if _MACROS_KEY not in env:
        env[_MACROS_KEY] = {}
    return env[_MACROS_KEY]


def eval_form(form: MalOForm, env: Dict[str, Any]) -> Any:
    """Evaluate a single form in the given environment."""
    if isinstance(form, Number):
        return form.value
    if isinstance(form, Str):
        return form.value
    if isinstance(form, Symbol):
        if form.name not in env:
            raise MalOError(f"Unknown symbol: {form.name!r}")
        return env[form.name]
    if isinstance(form, ListForm):
        return eval_list(form, env)
    raise MalOError(f"Cannot evaluate: {form}")


def eval_top_level(form: MalOForm, env: Dict[str, Any]) -> Any:
    """Evaluate a top-level form and convert loop control misuse to MalOError."""
    try:
        return eval_form(form, env)
    except _BreakSignal as exc:
        raise MalOError("break used outside of loop") from exc
    except _ContinueSignal as exc:
        raise MalOError("continue used outside of loop") from exc


def _macroexpand(form: MalOForm, env: Dict[str, Any]) -> MalOForm:
    """Repeatedly expand macros at the head of form until none apply."""
    while isinstance(form, ListForm) and form.elements:
        head = form.elements[0]
        if not isinstance(head, Symbol):
            return form
        macros = _get_macros(env)
        if head.name not in macros:
            return form
        macro_fn = macros[head.name]
        form = macro_fn(form, env)
    return form


def eval_list(form: ListForm, env: Dict[str, Any]) -> Any:
    """Evaluate an s-expression (special form or function call)."""
    form = _macroexpand(form, env)
    if not isinstance(form, ListForm):
        return eval_form(form, env)
    elements = form.elements
    if not elements:
        raise MalOError("Empty list () cannot be evaluated")

    head = elements[0]
    if not isinstance(head, Symbol):
        raise MalOError("Form must start with a symbol (special form or function)")
    name = head.name

    # --- Special forms (Hy-like) ---
    if name == "def" or name == "setv":
        if len(elements) != 3:
            raise MalOError("(def name value) requires exactly 3 elements")
        sym = elements[1]
        if not isinstance(sym, Symbol):
            raise MalOError("(def name value): name must be a symbol")
        value = eval_form(elements[2], env)
        env[sym.name] = value
        return value

    if name == "while":
        if len(elements) < 2:
            raise MalOError("(while test body...) requires at least 2 elements")
        result = None
        while eval_form(elements[1], env):
            try:
                for expr in elements[2:]:
                    result = eval_form(expr, env)
            except _ContinueSignal:
                continue
            except _BreakSignal:
                break
        return result

    if name == "for":
        if len(elements) < 3:
            raise MalOError("(for [name iterable] body...) requires at least 3 elements")
        binding_form = elements[1]
        if not isinstance(binding_form, ListForm) or len(binding_form.elements) != 2:
            raise MalOError("(for [name iterable] body...): binding must be [name iterable]")
        loop_sym = binding_form.elements[0]
        if not isinstance(loop_sym, Symbol):
            raise MalOError("(for [name iterable] body...): name must be a symbol")
        iterable_value = eval_form(binding_form.elements[1], env)
        try:
            iterator = iter(iterable_value)
        except TypeError as exc:
            raise MalOError("(for [name iterable] body...): iterable is not iterable") from exc

        result = None
        for item in iterator:
            inner = dict(env)
            inner[loop_sym.name] = item
            try:
                for expr in elements[2:]:
                    result = eval_form(expr, inner)
            except _ContinueSignal:
                continue
            except _BreakSignal:
                break
        return result

    if name == "break":
        if len(elements) != 1:
            raise MalOError("(break) does not accept arguments")
        raise _BreakSignal()

    if name == "continue":
        if len(elements) != 1:
            raise MalOError("(continue) does not accept arguments")
        raise _ContinueSignal()

    if name == "let":
        if len(elements) < 2:
            raise MalOError("(let [name value ...] body...) requires at least 2 elements")
        bindings_form = elements[1]
        if not isinstance(bindings_form, ListForm):
            raise MalOError("(let [name value ...] body...): bindings must be a list")
        bindings = bindings_form.elements
        if len(bindings) % 2 != 0:
            raise MalOError("(let [name value ...] ...): bindings must be name-value pairs")
        inner = dict(env)
        for i in range(0, len(bindings), 2):
            sym = bindings[i]
            if not isinstance(sym, Symbol):
                raise MalOError("(let bindings ...): binding name must be a symbol")
            inner[sym.name] = eval_form(bindings[i + 1], inner)
        result = None
        for expr in elements[2:]:
            result = eval_form(expr, inner)
        return result

    if name == "defn":
        if len(elements) < 3:
            raise MalOError("(defn name [params...] body...) requires at least 3 elements")
        fn_name = elements[1]
        if not isinstance(fn_name, Symbol):
            raise MalOError("(defn name ...): name must be a symbol")
        params_form = elements[2]
        if not isinstance(params_form, ListForm):
            raise MalOError("(defn name [params...] body...): params must be a list")
        params = [e.name for e in params_form.elements if isinstance(e, Symbol)]
        body = elements[3:]
        if not body:
            raise MalOError("(defn name [params...] body...): body cannot be empty")

        def fn(*args: Any) -> Any:
            if len(args) != len(params):
                raise MalOError(f"{fn_name.name} expects {len(params)} args, got {len(args)}")
            inner = dict(env)
            for k, v in zip(params, args):
                inner[k] = v
            result = None
            for expr in body:
                result = eval_form(expr, inner)
            return result

        env[fn_name.name] = fn
        return fn

    if name == "fn":
        if len(elements) < 3:
            raise MalOError("(fn [params...] body...) requires at least 3 elements")
        params_form = elements[1]
        if not isinstance(params_form, ListForm):
            raise MalOError("(fn [params...] body...): params must be a list")
        params = [e.name for e in params_form.elements if isinstance(e, Symbol)]
        body = elements[2:]

        def fn(*args: Any) -> Any:
            if len(args) != len(params):
                raise MalOError(f"Anonymous fn expects {len(params)} args, got {len(args)}")
            inner = dict(env)
            for k, v in zip(params, args):
                inner[k] = v
            result = None
            for expr in body:
                result = eval_form(expr, inner)
            return result

        return fn

    if name == "if":
        if len(elements) not in (3, 4):
            raise MalOError("(if test then else?) requires 3 or 4 elements")
        test = eval_form(elements[1], env)
        if test:
            return eval_form(elements[2], env)
        if len(elements) == 4:
            return eval_form(elements[3], env)
        return None

    if name == "do":
        result = None
        for expr in elements[1:]:
            result = eval_form(expr, env)
        return result

    if name == "quote":
        if len(elements) != 2:
            raise MalOError("(quote form) requires exactly 2 elements")
        return quote_to_value(elements[1])

    if name == "quasiquote":
        if len(elements) != 2:
            raise MalOError("(quasiquote form) requires exactly 2 elements")
        return _quasiquote_expand(elements[1], env)

    if name == "defmacro":
        if len(elements) < 3:
            raise MalOError("(defmacro name [params...] template) requires at least 3 elements")
        macro_name = elements[1]
        if not isinstance(macro_name, Symbol):
            raise MalOError("(defmacro name ...): name must be a symbol")
        params_form = elements[2]
        if not isinstance(params_form, ListForm):
            raise MalOError("(defmacro name [params...] template): params must be a list")
        params = [e.name for e in params_form.elements if isinstance(e, Symbol)]
        if len(elements) != 4:
            raise MalOError("(defmacro name [params...] template): exactly one template form required")
        template = elements[3]

        def macro_fn(form: ListForm, env: Dict[str, Any]) -> MalOForm:
            args = form.elements[1:]
            if len(args) != len(params):
                raise MalOError(f"Macro {macro_name.name} expects {len(params)} args, got {len(args)}")
            subs = dict(zip(params, args))
            return clone_and_substitute(template, subs)

        _get_macros(env)[macro_name.name] = macro_fn
        return macro_fn

    # --- Function call ---
    fn = eval_form(head, env)
    if not callable(fn):
        raise MalOError(f"Not callable: {head}")
    args = [eval_form(e, env) for e in elements[1:]]
    return fn(*args)


def quote_to_value(form: MalOForm) -> Any:
    """Turn a quoted form into a Python value (for quote)."""
    if isinstance(form, Number):
        return form.value
    if isinstance(form, Str):
        return form.value
    if isinstance(form, Symbol):
        return form.name  # or keep as symbol; Hy uses hy.models
    if isinstance(form, ListForm):
        return [quote_to_value(e) for e in form.elements]
    return form


def _quasiquote_expand(form: MalOForm, env: Dict[str, Any], in_quote: bool = False) -> Any:
    """Expand quasiquote: (unquote x) -> eval(x), (unquote-splice x) -> extend. (quote x) in template stays literal."""
    # (quote x) — treat as literal (expand x without processing unquote)
    if isinstance(form, ListForm) and len(form.elements) == 2:
        head = form.elements[0]
        if isinstance(head, Symbol) and head.name == "quote":
            return _quasiquote_expand(form.elements[1], env, in_quote=True)
    # (unquote x) / (unquote-splice x) — only when not inside quote
    if not in_quote and isinstance(form, ListForm) and len(form.elements) == 2:
        head = form.elements[0]
        if isinstance(head, Symbol):
            if head.name == "unquote":
                return eval_form(form.elements[1], env)
            if head.name == "unquote-splice":
                raise MalOError("unquote-splice only valid inside a list")
    # List: walk elements, splice on (unquote-splice x)
    if isinstance(form, ListForm):
        result: List[Any] = []
        for e in form.elements:
            if not in_quote and isinstance(e, ListForm) and len(e.elements) == 2:
                h = e.elements[0]
                if isinstance(h, Symbol) and h.name == "unquote-splice":
                    val = eval_form(e.elements[1], env)
                    if not isinstance(val, list):
                        raise MalOError("unquote-splice value must be a list")
                    result.extend(val)
                    continue
            result.append(_quasiquote_expand(e, env, in_quote))
        return result
    if isinstance(form, Symbol):
        return form.name
    if isinstance(form, Number):
        return form.value
    if isinstance(form, Str):
        return form.value
    return form


def default_env() -> Dict[str, Any]:
    """Build the default environment (Hy-like built-ins)."""
    env: Dict[str, Any] = {}

    def add(*args: Any) -> Any:
        if not args:
            return 0
        total = args[0]
        for x in args[1:]:
            total = total + x
        return total

    def sub(*args: Any) -> Any:
        if not args:
            raise MalOError("- requires at least one argument")
        if len(args) == 1:
            return -args[0]
        total = args[0]
        for x in args[1:]:
            total = total - x
        return total

    def mul(*args: Any) -> Any:
        if not args:
            return 1
        total = args[0]
        for x in args[1:]:
            total = total * x
        return total

    def div(*args: Any) -> Any:
        if len(args) < 2:
            raise MalOError("/ requires at least two arguments")
        total = args[0]
        for x in args[1:]:
            total = total / x
        return total

    env["+"] = add
    env["-"] = sub
    env["*"] = mul
    env["/"] = div
    env["print"] = lambda *a: print(*a) or (None if len(a) == 0 else a[-1])
    env["="] = lambda a, b: a == b
    env["<"] = lambda a, b: a < b
    env["<="] = lambda a, b: a <= b
    env[">"] = lambda a, b: a > b
    env[">="] = lambda a, b: a >= b
    env["list"] = lambda *a: list(a)
    env["range"] = lambda *a: list(range(*a))
    env["first"] = lambda x: x[0] if x else None
    env["rest"] = lambda x: list(x[1:]) if x else []
    env["len"] = len
    env["None"] = None
    env["True"] = True
    env["False"] = False
    return env
