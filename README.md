# MalO

A small [Hy](https://hylang.org/)-like Lisp interpreter that runs on Python 3.13+. Programs are tab-indented forms with nested parentheses for arguments, plus Python interop, macros, and keyword arguments.

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)

## Install and run

```bash
uv sync
uv run malo path/to/file.malo
```

`python -m malo path/to/file.malo` does the same thing. Passing no file prints usage and exits with status 2.

Try the bundled example:

```bash
uv run malo examples/main.malo
```

## Syntax

Each non-empty line is a form (a call or special form). Nested arguments on the same line use `(...)`, `[...]`, or `{key val ...}`. Comments start with `;` and run to the end of the line.

**Block structure uses tab indentation** (spaces do not count). Dedenting closes the block. Do not wrap a block in parentheses.

```
while (< i 10)
	print i
	update i + 1
```

Reader macros:

| Sugar | Expands to |
| --- | --- |
| `` `form `` | `(quasiquote form)` |
| `~form` | `(unquote form)` |
| `~@form` | `(unquote-splice form)` |

## Language

### Values and builtins

`True`, `False`, and `None` are bound. Arithmetic and comparison are Python-backed: `+`, `-`, `*`, `/`, `=`, `<`, `<=`, `>`, `>=`. Also available: `print`, `list`, `range`, `first`, `rest`, `len`.

### Bindings and functions

```
setv x 100
def y 1

defn greet [name &optional [suffix "!"]]
	print "Hello," name suffix

greet "MalO"
greet :name "MalO"

let [a 1 b 2]
	print (+ a b)
```

`setv` and `def` are aliases. `fn` is an anonymous function. `update` applies a function to the current value of a symbol and writes it back: `update x + 100` sets `x` to `(+ x 100)`.

Parameter lists are `[required... &optional opt... &rest name? &keys name?]`:

- `&optional name` or `&optional [name default]`
- bare `&rest` binds extra positionals to `args`
- bare `&keys` binds leftover keywords to `keys`

Calls take positional args and `:key value` pairs. Keywords may fill named parameters (`:name "MalO"`) or go into `&keys`.

### Control flow

```
if test then else?
do body...
while test body...
for [pat iterable] body...
break
continue
assert test msg?
```

`for` can destructure:

```
for [[k v] (.items d)]
	print k v
```

`break` and `continue` only work inside `while` / `for`.

### Python interop

```
import math
import math :as mt
from math :import sin cos
from math :import sqrt :as square_root
from math :import *
from builtins :import str type

print (math.sqrt 2)
print (.format "Hello, {}!" "world")
```

Dotted names resolve as attribute chains (`math.sqrt`). `(.method obj args...)` calls a method. `(. obj attr)` and `(. obj (method args...))` do the same with an explicit object first.

### Macros and quoting

```
quote form
quasiquote form

defmacro setv-str [var val]
	setv var (str val)
```

Macros substitute parameter forms into a template (they do not evaluate the body as Python). Use `` ` `` / `~` / `~@` for quasiquote, unquote, and splice.

## Project layout

```
src/malo/          interpreter (tokenizer, parser, AST, eval, CLI)
examples/main.malo sample program
```
