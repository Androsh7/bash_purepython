"""PurePython implementation of the bash tr command"""

# Standard libraries
import sys
from argparse import ArgumentParser

# Project libraries
from bash_purepython._color import print_error


def expand(spec: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(spec):
        if i + 2 < len(spec) and spec[i + 1] == "-":
            start, end = ord(spec[i]), ord(spec[i + 2])
            step = 1 if end >= start else -1
            for c in range(start, end + step, step):
                out.append(chr(c))
            i += 3
        else:
            out.append(spec[i])
            i += 1
    return "".join(out)


def main():
    parser = ArgumentParser(prog="tr", description="Translate or delete characters from stdin")
    parser.add_argument("-d", "--delete", action="store_true", help="Delete characters in set1")
    parser.add_argument("-s", "--squeeze-repeats", action="store_true", help="Squeeze runs in the last operand set")
    parser.add_argument("-c", "--complement", action="store_true", help="Use the complement of set1")
    parser.add_argument("set1", help="First character set")
    parser.add_argument("set2", nargs="?", default="", help="Second character set")
    args = parser.parse_args()

    s1 = expand(args.set1)
    s2 = expand(args.set2)
    text = sys.stdin.read()

    if args.complement:
        keep = set(s1)
        s1 = "".join(chr(c) for c in range(0x110000) if chr(c) not in keep and chr(c).isprintable())

    if args.delete:
        drop = set(s1)
        text = "".join(ch for ch in text if ch not in drop)
    elif s2:
        if len(s2) < len(s1):
            s2 = s2 + s2[-1] * (len(s1) - len(s2))
        table = str.maketrans(s1, s2[: len(s1)])
        text = text.translate(table)
    elif not args.squeeze_repeats:
        print_error("tr: missing operand")

    if args.squeeze_repeats:
        target = s2 if s2 else s1
        squeeze_set = set(target)
        out: list[str] = []
        prev: str | None = None
        for ch in text:
            if ch == prev and ch in squeeze_set:
                continue
            out.append(ch)
            prev = ch
        text = "".join(out)

    sys.stdout.write(text)


if __name__ == "__main__":
    main()
