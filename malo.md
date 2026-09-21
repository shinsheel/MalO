---
name: MalO
filename: learnmalo.malo
contributors:
    - ["Vladislav Gavrilov"]
---

MalO is a small [Hy](https://hylang.org/)-like Lisp on Python 3.13+.
Each non-empty line is a form. Tab indentation opens a body (spaces do not
count). Parentheses, brackets, and braces nest arguments on the same line —
do not wrap a block in parentheses.

Run a file with `uv run malo path/to/file.malo`.

```
; Semicolon comments, like other Lisps

;; Syntax
; Lisp programs are made of forms. Nested arguments look like
; (function arg1 arg2). A whole line is already a form, so write:
print "hello world"

; Tabs indent a body under the previous form. Dedenting closes it.
setv i 0
while (< i 3)
	print i
	update i + 1
; => 0
; => 1
; => 2

;; Simple data types
; These are the same as their Python counterparts
print 42 ; => 42
print 3.14 ; => 3.14
print -2 ; => -2
print 1.5e-1 ; => 0.15
print True ; => True
print False ; => False
print None ; => None
print "hello world" ; => hello world
print "say \"hi\"" ; => say "hi"
print "line\nnext" ; => line / next

;; Arithmetic and comparison
; The operator is applied to all arguments, like other Lisps
print (+ 4 1) ; => 5
print (+ 4 1 2 3) ; => 10
print (- 2 1) ; => 1
print (- 3) ; => -3
print (* 4 2) ; => 8
print (/ 4 2) ; => 2.0
print (+ 2 (* 4 2)) ; => 10
print (= 5 4) ; => False
print (< 1 2) ; => True
print (<= 1 1) ; => True
print (> 2 1) ; => True
print (>= 2 2) ; => True

;; Variables
; Bind with setv or def (aliases). update applies a function to a place
setv a 42
def b 1
print a b ; => 42 1
update a + 8
print a ; => 50
defn double [x]
	* x 2
update a double
print a ; => 100

; let creates local bindings; later bindings can use earlier ones
let [x 1 y (+ x 2)]
	print x y ; => 1 3

; do evaluates forms in order and returns the last value
do
	print "seq-a"
	print "seq-b"

;; Lists and dicts
; Build lists with list (a bare [1 2 3] would try to call 1)
print (list 1 2 3) ; => [1, 2, 3]
print (len (list 1 2 3)) ; => 3
print (first (list 1 2 3)) ; => 1
print (rest (list 1 2 3)) ; => [2, 3]
print (range 3) ; => [0, 1, 2]

; Dicts are {key val ...}; keys and values are evaluated
setv scores {"a" 1 "b" 2}
print scores ; => {'a': 1, 'b': 2}
print {None "nil" 2 "two"} ; => {None: 'nil', 2: 'two'}
print {"outer" {"inner" 1}} ; => {'outer': {'inner': 1}}
print {(+ 1 2) "three"} ; => {3: 'three'}

;; Functions
; defn defines a named function; the last form is the return value
defn greet [name]
	print "hello" name
greet "bilbo" ; => hello bilbo

; &optional name, or &optional [name default]. Missing optionals are None
defn foolists [arg1 &optional [arg2 2]]
	list arg1 arg2
print (foolists 3) ; => [3, 2]
print (foolists 10 3) ; => [10, 3]

defn maybe [x &optional y]
	print x y
maybe 1 ; => 1 None

; &rest collects extra positionals (bare &rest binds args)
; &keys collects leftover keywords (bare &keys binds keys)
defn fancy [wow &rest extras &keys props]
	print wow extras props
fancy "horse" "tall" :mane "spectacular"
; => horse ['tall'] {'mane': 'spectacular'}

; Calls take :key value pairs. Keywords may fill named parameters
defn hello [name &optional [suffix "!"]]
	print "Hello," name suffix
hello "MalO"
hello :name "MalO"
hello "MalO" :suffix "?"
hello :suffix "~" :name "MalO"

; Combine required, optional, rest, and keys
defn flex [a &optional [b 1] extra &rest xs &keys ks]
	print a b extra xs ks
flex 10 ; => 10 1 None [] {}
flex 10 20 30 40 ; => 10 20 30 [40] {}
flex 10 :b 2 :extra 3 :z 9 ; => 10 2 3 [] {'z': 9}

; Anonymous functions use fn. They close over the defining environment
setv square
	fn [x]
		* x x
print (square 4) ; => 16

setv add-n
	let [n 10]
		fn [x]
			+ x n
print (add-n 5) ; => 15

;; Control flow
; if: test then else?. False without else returns None
print (if True "welcome" "go away") ; => welcome
print (if False "welcome" "go away") ; => go away
print (if True "only-then") ; => only-then
print (if False "only-then") ; => None

; A two-line body under if is then / else
if False
	print "yes"
	print "no" ; => no

assert (= (* 2 2) 4)
assert True "still true"

; for binds a name or a destructuring pattern
for [n (range 4)]
	print n
; => 0 1 2 3

for [[k v] (.items scores)]
	print k v

; Nested patterns unpack nested lists
setv nested (list (list (list 1 2) 3))
for [[[a b] c] nested]
	print a b c ; => 1 2 3

; break and continue work inside while / for
setv i 0
while True
	if (>= i 3)
		break
	update i + 1
print i ; => 3

for [n (range 4)]
	if (= n 1)
		continue
	print n
; => 0 2 3

;; Python interop
import math
import math :as mt os.path
from math :import sin cos
from math :import sqrt :as square_root
from math :import *
from builtins :import str type
from os.path :import join

print (math.sqrt 2) ; => 1.414...
print (mt.sqrt 9) ; => 3.0
print (sin 0) ; => 0.0
print (square_root 4) ; => 2.0
print (os.path.join "a" "b") ; => a/b
print (join "a" "b") ; => a/b

; Dotted names are attribute chains. Methods: (.method obj args...)
; or (. obj attr) and (. obj (method args...))
print (. math pi) ; => 3.14159...
print (. "hello" (upper)) ; => HELLO
print (. "ab" (replace "a" "z")) ; => zb
print (.format "Hello, {}!" "world") ; => Hello, world!
print (.format "Hello, {who}!" :who "MalO") ; => Hello, MalO!
print (. "Hello, {who}!" (format :who "MalO")) ; => Hello, MalO!
; A computed head is just another form
print ((. "Hello, {}!" format) "MalO") ; => Hello, MalO!

;; Quote, quasiquote, macros
; quote returns data. ` ~ ~@ are quasiquote / unquote / unquote-splice
print (quote (a b c)) ; => ['a', 'b', 'c']
print (quote {a 1}) ; => {'a': 1}

setv who "MalO"
setv tags (list "scp-671" "scp-1471")
print `(hello ~who score ~(+ 10 20) ~@tags)
; => ['hello', 'MalO', 'score', 30, 'scp-671', 'scp-1471']
print (quasiquote (hello (unquote who) (unquote-splice tags)))
print `(literal (quote (+ 1 2)) computed ~(+ 1 2))
; => ['literal', ['+', 1, 2], 'computed', 3]
print `{who ~who n ~(+ 1 2)} ; => {'who': 'MalO', 'n': 3}

; defmacro substitutes parameter forms into a template (it does not eval
; the body as Python). Expansion can chain into another macro
defmacro setv-str [var val]
	setv var (str val)
setv-str s10 10
print (type s10) ; => <class 'str'>
setv-str :var s11 :val 11

defmacro show2 [x]
	print x x
defmacro show2! [x]
	show2 x
show2! "echo" ; => echo echo

defmacro tag-print [x &optional [label "val"]]
	print label x
tag-print 1 ; => val 1
tag-print 1 :label "num" ; => num 1

defmacro quoted-args [&rest xs]
	quote xs
print (quoted-args 1 2 3) ; => [1, 2, 3]

defmacro dump-keys [&keys opts] opts
print (dump-keys :a 1 :b 2) ; => {'a': 1, 'b': 2}
```

### Further Reading

This is a tour of MalO, not a language spec.

- [README.md](README.md) in this repo
- [examples/main.malo](examples/main.malo)
- MalO is Hy-shaped; Hy's docs are at [hylang.org](https://hylang.org/hy/doc)
