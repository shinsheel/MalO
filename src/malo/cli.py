import sys
from pathlib import Path

from .eval import default_env, eval_top_level
from .parser import parse_all
from .tokenizer import tokenize_with_indent


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: malo <file.malo>", file=sys.stderr)
        raise SystemExit(2)
    code = Path(args[0]).read_text()
    env = default_env()
    for form in parse_all(list(tokenize_with_indent(code))):
        eval_top_level(form, env)


if __name__ == "__main__":
    main()
