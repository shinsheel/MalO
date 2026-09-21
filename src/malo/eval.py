"""Evaluate MalO AST (Hy-like interpreter)."""
import importlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .malo_ast import DictForm, ListForm, MalOForm, Number, Str, Symbol, clone_and_substitute

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


@dataclass
class _ParamSpec:
    """Parsed parameter list: required, optional, &rest, and &keys collector."""
    required: List[str]
    optional: List[Tuple[str, Optional[MalOForm]]]  # default None => bind None
    rest: Optional[str] = None  # &rest name (bare &rest => "args")
    keys: Optional[str] = None  # &keys name (bare &keys => "keys")


def _get_macros(env: Dict[str, Any]) -> Dict[str, Any]:
    if _MACROS_KEY not in env:
        env[_MACROS_KEY] = {}
    return env[_MACROS_KEY]


def _parse_params(params_form: ListForm, context: str) -> _ParamSpec:
    """Parse [required... &optional opt... &rest name? &keys name?]."""
    required: List[str] = []
    optional: List[Tuple[str, Optional[MalOForm]]] = []
    rest: Optional[str] = None
    keys: Optional[str] = None
    mode = "required"
    i = 0
    elems = params_form.elements

    while i < len(elems):
        elem = elems[i]
        if isinstance(elem, Symbol) and elem.name.startswith("&"):
            if elem.name == "&optional":
                if mode != "required":
                    raise MalOError(f"{context}: &optional must precede &rest/&keys")
                mode = "optional"
                i += 1
                continue
            if elem.name == "&rest":
                if mode in ("rest", "keys"):
                    raise MalOError(f"{context}: &rest may appear only once and before &keys")
                mode = "rest"
                i += 1
                if i < len(elems):
                    rest_name = elems[i]
                    if isinstance(rest_name, Symbol) and not rest_name.name.startswith("&"):
                        rest = rest_name.name
                        i += 1
                    else:
                        rest = "args"
                else:
                    rest = "args"
                continue
            if elem.name == "&keys":
                if mode == "keys":
                    raise MalOError(f"{context}: &keys may appear only once")
                mode = "keys"
                i += 1
                if i < len(elems):
                    keys_name = elems[i]
                    if isinstance(keys_name, Symbol) and not keys_name.name.startswith("&"):
                        keys = keys_name.name
                        i += 1
                    else:
                        keys = "keys"
                else:
                    keys = "keys"
                if i < len(elems):
                    raise MalOError(f"{context}: nothing allowed after &keys")
                continue
            raise MalOError(f"{context}: unsupported parameter marker {elem.name!r}")

        if mode == "required":
            if not isinstance(elem, Symbol):
                raise MalOError(f"{context}: required param must be a symbol")
            required.append(elem.name)
        elif mode == "optional":
            # optional: name  or  [name default]
            if isinstance(elem, Symbol):
                optional.append((elem.name, None))
            elif isinstance(elem, ListForm):
                if len(elem.elements) != 2 or not isinstance(elem.elements[0], Symbol):
                    raise MalOError(f"{context}: optional param must be [name default]")
                optional.append((elem.elements[0].name, elem.elements[1]))
            else:
                raise MalOError(f"{context}: invalid optional param")
        elif mode == "rest":
            raise MalOError(f"{context}: nothing allowed after &rest name (use &keys for kwargs)")
        else:
            raise MalOError(f"{context}: nothing allowed after &keys")
        i += 1

    return _ParamSpec(required=required, optional=optional, rest=rest, keys=keys)


def _is_keyword(form: MalOForm) -> bool:
    """True for keyword symbols like :name (not bare ':')."""
    return isinstance(form, Symbol) and form.name.startswith(":") and len(form.name) > 1


def _split_call_args(
    elements: List[MalOForm],
) -> Tuple[List[MalOForm], Dict[str, MalOForm]]:
    """Split call args into positionals and :key value keyword pairs."""
    positional: List[MalOForm] = []
    kwargs: Dict[str, MalOForm] = {}
    i = 0
    while i < len(elements):
        elem = elements[i]
        if _is_keyword(elem):
            assert isinstance(elem, Symbol)
            key = elem.name[1:]
            if i + 1 >= len(elements):
                raise MalOError(f"Keyword :{key} missing value")
            if key in kwargs:
                raise MalOError(f"Duplicate keyword argument :{key}")
            kwargs[key] = elements[i + 1]
            i += 2
        else:
            if kwargs:
                raise MalOError("Positional argument after keyword argument")
            positional.append(elem)
            i += 1
    return positional, kwargs


def _bind_params(
    spec: _ParamSpec,
    args: List[Any],
    env: Dict[str, Any],
    fn_label: str,
    kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Bind args/kwargs into a new env; fill missing optionals; collect &rest/&keys."""
    kwargs = dict(kwargs or {})
    known = set(spec.required) | {name for name, _ in spec.optional}
    if spec.keys is None:
        for key in kwargs:
            if key not in known:
                raise MalOError(f"{fn_label} got unexpected keyword argument :{key}")

    inner = dict(env)
    remaining = list(args)

    for name in spec.required:
        if remaining:
            if name in kwargs:
                raise MalOError(f"{fn_label} got multiple values for argument {name!r}")
            inner[name] = remaining.pop(0)
        elif name in kwargs:
            inner[name] = kwargs.pop(name)
        else:
            raise MalOError(f"{fn_label} missing required argument {name!r}")

    for name, default_form in spec.optional:
        if remaining:
            if name in kwargs:
                raise MalOError(f"{fn_label} got multiple values for argument {name!r}")
            inner[name] = remaining.pop(0)
        elif name in kwargs:
            inner[name] = kwargs.pop(name)
        elif default_form is None:
            inner[name] = None
        else:
            inner[name] = eval_form(default_form, inner)

    if remaining and spec.rest is None:
        max_args = len(spec.required) + len(spec.optional)
        raise MalOError(
            f"{fn_label} expects at most {max_args} positional args, "
            f"got {len(args)}"
        )

    if spec.rest is not None:
        inner[spec.rest] = remaining
    if spec.keys is not None:
        inner[spec.keys] = kwargs
    return inner


def _bind_macro_params(
    spec: _ParamSpec,
    args: List[MalOForm],
    macro_name: str,
    kwargs: Optional[Dict[str, MalOForm]] = None,
) -> Dict[str, MalOForm]:
    """Bind macro call args/kwargs (forms) including &optional / &rest / &keys."""
    kwargs = dict(kwargs or {})
    known = set(spec.required) | {name for name, _ in spec.optional}
    if spec.keys is None:
        for key in kwargs:
            if key not in known:
                raise MalOError(
                    f"Macro {macro_name} got unexpected keyword argument :{key}"
                )

    subs: Dict[str, MalOForm] = {}
    remaining = list(args)

    for name in spec.required:
        if remaining:
            if name in kwargs:
                raise MalOError(
                    f"Macro {macro_name} got multiple values for argument {name!r}"
                )
            subs[name] = remaining.pop(0)
        elif name in kwargs:
            subs[name] = kwargs.pop(name)
        else:
            raise MalOError(f"Macro {macro_name} missing required argument {name!r}")

    for pname, default_form in spec.optional:
        if remaining:
            if pname in kwargs:
                raise MalOError(
                    f"Macro {macro_name} got multiple values for argument {pname!r}"
                )
            subs[pname] = remaining.pop(0)
        elif pname in kwargs:
            subs[pname] = kwargs.pop(pname)
        elif default_form is not None:
            subs[pname] = default_form
        else:
            subs[pname] = Symbol("None")

    if remaining and spec.rest is None:
        max_args = len(spec.required) + len(spec.optional)
        raise MalOError(
            f"Macro {macro_name} expects at most {max_args} positional args, "
            f"got {len(args)}"
        )

    if spec.rest is not None:
        subs[spec.rest] = ListForm(remaining)
    if spec.keys is not None:
        elems: List[MalOForm] = []
        for key, val in kwargs.items():
            elems.append(Str(key))
            elems.append(val)
        subs[spec.keys] = DictForm(elems)
    return subs


def _load_module(name: str) -> Any:
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise MalOError(f"Cannot import module {name!r}") from exc


def _star_import(module: Any, env: Dict[str, Any]) -> None:
    """Bind public names from module into env (respects __all__)."""
    if hasattr(module, "__all__"):
        names = list(module.__all__)
    else:
        names = [n for n in dir(module) if not n.startswith("_")]
    for name in names:
        try:
            env[name] = getattr(module, name)
        except AttributeError as exc:
            raise MalOError(
                f"Module has no attribute {name!r} (from __all__)"
            ) from exc


def _eval_import(forms: List[MalOForm], env: Dict[str, Any]) -> None:
    """(import mod) | (import mod :as alias) | multiple such clauses."""
    if not forms:
        raise MalOError("(import ...) requires at least one module")
    i = 0
    while i < len(forms):
        mod_sym = forms[i]
        if not isinstance(mod_sym, Symbol):
            raise MalOError("(import ...): module name must be a symbol")
        i += 1
        alias: Optional[str] = None
        if i < len(forms) and isinstance(forms[i], Symbol) and forms[i].name == ":as":
            i += 1
            if i >= len(forms) or not isinstance(forms[i], Symbol):
                raise MalOError("(import mod :as alias): alias must be a symbol")
            alias = forms[i].name
            i += 1
        module = _load_module(mod_sym.name)
        if alias is not None:
            env[alias] = module
        else:
            top = mod_sym.name.split(".")[0]
            env[top] = _load_module(top) if "." in mod_sym.name else module
    return None


def _eval_from(forms: List[MalOForm], env: Dict[str, Any]) -> None:
    """(from mod :import names...) | (from mod :import *) | name :as alias."""
    if len(forms) < 3:
        raise MalOError("(from module :import names...) requires module and names")
    mod_sym = forms[0]
    if not isinstance(mod_sym, Symbol):
        raise MalOError("(from ...): module name must be a symbol")
    import_kw = forms[1]
    if not isinstance(import_kw, Symbol) or import_kw.name != ":import":
        raise MalOError("(from module :import ...): expected :import")
    names = forms[2:]
    if not names:
        raise MalOError("(from ... :import ...) requires at least one name")

    module = _load_module(mod_sym.name)

    if (
        len(names) == 1
        and isinstance(names[0], Symbol)
        and names[0].name == "*"
    ):
        _star_import(module, env)
        return None

    i = 0
    while i < len(names):
        name_sym = names[i]
        if not isinstance(name_sym, Symbol):
            raise MalOError("(from ... :import ...): name must be a symbol")
        if name_sym.name == "*":
            raise MalOError("(from ... :import *): * must be the only name")
        i += 1
        bind_as = name_sym.name
        if i < len(names) and isinstance(names[i], Symbol) and names[i].name == ":as":
            i += 1
            if i >= len(names) or not isinstance(names[i], Symbol):
                raise MalOError("(from ... :import name :as alias): alias must be a symbol")
            bind_as = names[i].name
            i += 1
        try:
            env[bind_as] = getattr(module, name_sym.name)
        except AttributeError as exc:
            raise MalOError(
                f"Module {mod_sym.name!r} has no attribute {name_sym.name!r}"
            ) from exc
    return None


def _resolve_symbol(name: str, env: Dict[str, Any]) -> Any:
    """Look up a symbol; dotted names use getattr chains (math.sqrt)."""
    if name in env:
        return env[name]
    if "." in name and not name.startswith("."):
        parts = name.split(".")
        if parts[0] not in env:
            raise MalOError(f"Unknown symbol: {name!r}")
        obj = env[parts[0]]
        for part in parts[1:]:
            try:
                obj = getattr(obj, part)
            except AttributeError as exc:
                raise MalOError(
                    f"Object has no attribute {part!r} (in {name!r})"
                ) from exc
        return obj
    raise MalOError(f"Unknown symbol: {name!r}")


def _bind_pattern(pat: MalOForm, value: Any, env: Dict[str, Any], context: str) -> None:
    """Bind a symbol or [pat ...] destructuring pattern to value in env."""
    if isinstance(pat, Symbol):
        env[pat.name] = value
        return
    if isinstance(pat, ListForm):
        try:
            values = list(value)
        except TypeError as exc:
            raise MalOError(f"{context}: cannot destructure non-iterable value") from exc
        if len(values) != len(pat.elements):
            raise MalOError(
                f"{context}: pattern length {len(pat.elements)} != value length {len(values)}"
            )
        for sub_pat, sub_val in zip(pat.elements, values):
            _bind_pattern(sub_pat, sub_val, env, context)
        return
    raise MalOError(f"{context}: invalid destructuring pattern")


def eval_form(form: MalOForm, env: Dict[str, Any]) -> Any:
    """Evaluate a single form in the given environment."""
    if isinstance(form, Number):
        return form.value
    if isinstance(form, Str):
        return form.value
    if isinstance(form, Symbol):
        return _resolve_symbol(form.name, env)
    if isinstance(form, DictForm):
        elems = form.elements
        if len(elems) % 2 != 0:
            raise MalOError("Dict literal requires an even number of elements")
        return {
            eval_form(elems[i], env): eval_form(elems[i + 1], env)
            for i in range(0, len(elems), 2)
        }
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
    if isinstance(head, Symbol):
        name = head.name

        # (.method obj args...) => call getattr(obj, method)(*args)
        if name.startswith(".") and name != ".":
            if len(elements) < 2:
                raise MalOError(f"({name} object args...) requires an object")
            attr = name[1:]
            obj = eval_form(elements[1], env)
            try:
                method = getattr(obj, attr)
            except AttributeError as exc:
                raise MalOError(f"Object has no attribute {attr!r}") from exc
            pos_forms, kw_forms = _split_call_args(elements[2:])
            call_args = [eval_form(e, env) for e in pos_forms]
            call_kwargs = {k: eval_form(v, env) for k, v in kw_forms.items()}
            return method(*call_args, **call_kwargs)

        # (. object attr...) => getattr chain; (. obj (method args...)) => method call
        if name == ".":
            if len(elements) < 3:
                raise MalOError("(. object attribute...) requires at least 3 elements")
            obj = eval_form(elements[1], env)
            for attr_form in elements[2:]:
                if isinstance(attr_form, Symbol):
                    try:
                        obj = getattr(obj, attr_form.name)
                    except AttributeError as exc:
                        raise MalOError(
                            f"Object has no attribute {attr_form.name!r}"
                        ) from exc
                elif isinstance(attr_form, ListForm) and attr_form.elements:
                    method_sym = attr_form.elements[0]
                    if not isinstance(method_sym, Symbol):
                        raise MalOError(
                            "(. object (method ...)): method must be a symbol"
                        )
                    try:
                        method = getattr(obj, method_sym.name)
                    except AttributeError as exc:
                        raise MalOError(
                            f"Object has no attribute {method_sym.name!r}"
                        ) from exc
                    pos_forms, kw_forms = _split_call_args(attr_form.elements[1:])
                    call_args = [eval_form(a, env) for a in pos_forms]
                    call_kwargs = {k: eval_form(v, env) for k, v in kw_forms.items()}
                    obj = method(*call_args, **call_kwargs)
                else:
                    raise MalOError(
                        "(. object attribute...): attribute must be a symbol or (method ...)"
                    )
            return obj

        # --- Special forms (Hy-like) ---
        if name == "import":
            return _eval_import(elements[1:], env)

        if name == "from":
            return _eval_from(elements[1:], env)

        # (update place fn args...) => (setv place (fn place args...))
        if name == "update":
            if len(elements) < 3:
                raise MalOError("(update place fn args...) requires at least 3 elements")
            place = elements[1]
            if not isinstance(place, Symbol):
                raise MalOError("(update ...): place must be a symbol")
            fn = eval_form(elements[2], env)
            if not callable(fn):
                raise MalOError(f"Not callable: {elements[2]}")
            current = _resolve_symbol(place.name, env)
            args = [eval_form(e, env) for e in elements[3:]]
            value = fn(current, *args)
            env[place.name] = value
            return value

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
            loop_pat = binding_form.elements[0]
            if not isinstance(loop_pat, (Symbol, ListForm)):
                raise MalOError(
                    "(for [name iterable] body...): name must be a symbol or [names...]"
                )
            iterable_value = eval_form(binding_form.elements[1], env)
            try:
                iterator = iter(iterable_value)
            except TypeError as exc:
                raise MalOError("(for [name iterable] body...): iterable is not iterable") from exc

            result = None
            for item in iterator:
                inner = dict(env)
                _bind_pattern(loop_pat, item, inner, "(for ...)")
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
            param_spec = _parse_params(params_form, "(defn ...)")
            body = elements[3:]
            if not body:
                raise MalOError("(defn name [params...] body...): body cannot be empty")

            def fn(*args: Any, **kwargs: Any) -> Any:
                inner = _bind_params(
                    param_spec, list(args), env, fn_name.name, kwargs=kwargs
                )
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
            param_spec = _parse_params(params_form, "(fn ...)")
            body = elements[2:]

            def fn(*args: Any, **kwargs: Any) -> Any:
                inner = _bind_params(
                    param_spec, list(args), env, "Anonymous fn", kwargs=kwargs
                )
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

        if name == "assert":
            if len(elements) not in (2, 3):
                raise MalOError("(assert test msg?) requires 2 or 3 elements")
            if not eval_form(elements[1], env):
                if len(elements) == 3:
                    raise AssertionError(eval_form(elements[2], env))
                raise AssertionError()
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
            param_spec = _parse_params(params_form, "(defmacro ...)")
            if len(elements) != 4:
                raise MalOError("(defmacro name [params...] template): exactly one template form required")
            template = elements[3]

            def macro_fn(form: ListForm, env: Dict[str, Any]) -> MalOForm:
                pos_forms, kw_forms = _split_call_args(list(form.elements[1:]))
                subs = _bind_macro_params(
                    param_spec, pos_forms, macro_name.name, kwargs=kw_forms
                )
                return clone_and_substitute(template, subs)

            _get_macros(env)[macro_name.name] = macro_fn
            return macro_fn

    # --- Function call (head may be any form, e.g. ((. s format) args...)) ---
    fn = eval_form(head, env)
    if not callable(fn):
        raise MalOError(f"Not callable: {head}")
    pos_forms, kw_forms = _split_call_args(elements[1:])
    args = [eval_form(e, env) for e in pos_forms]
    kwargs = {k: eval_form(v, env) for k, v in kw_forms.items()}
    return fn(*args, **kwargs)


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
    if isinstance(form, DictForm):
        elems = form.elements
        if len(elems) % 2 != 0:
            raise MalOError("Dict literal requires an even number of elements")
        return {
            quote_to_value(elems[i]): quote_to_value(elems[i + 1])
            for i in range(0, len(elems), 2)
        }
    return form


def _quasiquote_expand_elements(
    elements: List[MalOForm], env: Dict[str, Any], in_quote: bool
) -> List[Any]:
    """Walk quasiquote elements, splicing (unquote-splice x) into the result."""
    result: List[Any] = []
    for e in elements:
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
                raise MalOError("unquote-splice only valid inside a list or dict")
    if isinstance(form, ListForm):
        return _quasiquote_expand_elements(form.elements, env, in_quote)
    if isinstance(form, DictForm):
        elems = _quasiquote_expand_elements(form.elements, env, in_quote)
        if len(elems) % 2 != 0:
            raise MalOError("Dict literal requires an even number of elements")
        return {elems[i]: elems[i + 1] for i in range(0, len(elems), 2)}
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
