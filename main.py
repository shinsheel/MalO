from eval import default_env, eval_top_level
from parser import parse_all
from tokenizer import tokenize_with_indent


def main():
    with open("main.malo", "r") as file:
        code = file.read()
    tokens = list(tokenize_with_indent(code))
    forms = parse_all(tokens)
    env = default_env()
    for form in forms:
        eval_top_level(form, env)


if __name__ == "__main__":
    main()
