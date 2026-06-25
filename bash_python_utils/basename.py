"""PurePython implementation of the bash basename command"""

# Standard libraries
from argparse import ArgumentParser
from pathlib import PurePosixPath


def main():
    parser = ArgumentParser(prog="basename", description="Strip directory and optional suffix from a filename")
    parser.add_argument("-s", "--suffix", default=None, help="Suffix to remove")
    parser.add_argument("-a", "--multiple", action="store_true", help="Support multiple arguments")
    parser.add_argument("name", help="Path")
    parser.add_argument("extra", nargs="*", help="Suffix (legacy) or extra paths with -a")
    args = parser.parse_args()

    names = [args.name]
    suffix = args.suffix
    if args.multiple:
        names += args.extra
    elif args.extra:
        suffix = args.extra[0]

    for name in names:
        base = PurePosixPath(name.replace("\\", "/")).name
        if suffix and base.endswith(suffix) and base != suffix:
            base = base[: -len(suffix)]
        print(base)


if __name__ == "__main__":
    main()
