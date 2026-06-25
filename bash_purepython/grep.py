"""PurePython implementation of the bash grep command"""

# Standard libraries
import re
import sys
from argparse import ArgumentParser
from pathlib import Path

# Project libraries
from bash_purepython._color import print_error


def iter_files(paths: list[str], recursive: bool):
    if not paths:
        yield "-", sys.stdin.read()
        return
    for path_str in paths:
        path = Path(path_str)
        if not path.exists():
            print_error(f"{path}: No such file or directory")
        if path.is_dir():
            if not recursive:
                print_error(f"{path}: Is a directory (use -r)")
            for child in path.rglob("*"):
                if child.is_file():
                    yield str(child), child.read_text(encoding="utf-8", errors="replace")
        else:
            yield path_str, path.read_text(encoding="utf-8", errors="replace")


def main():
    parser = ArgumentParser(prog="grep", description="Search lines matching a pattern")
    parser.add_argument("-i", "--ignore-case", action="store_true", help="Case insensitive match")
    parser.add_argument("-v", "--invert-match", action="store_true", help="Select non-matching lines")
    parser.add_argument("-n", "--line-number", action="store_true", help="Prefix lines with line number")
    parser.add_argument("-c", "--count", action="store_true", help="Print only a count of matching lines per file")
    parser.add_argument("-r", "-R", "--recursive", action="store_true", help="Recurse into directories")
    parser.add_argument("-F", "--fixed-strings", action="store_true", help="Treat pattern as a fixed string")
    parser.add_argument("-l", "--files-with-matches", action="store_true", help="Print only names of matching files")
    parser.add_argument("-H", "--with-filename", action="store_true", help="Always print filename")
    parser.add_argument("pattern", help="Regular expression to match")
    parser.add_argument("paths", nargs="*", help="Files to search (stdin if none)")
    args = parser.parse_args()

    pattern = re.escape(args.pattern) if args.fixed_strings else args.pattern
    flags = re.IGNORECASE if args.ignore_case else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as exc:
        print_error(f"invalid pattern: {exc}")

    files = list(iter_files(args.paths, args.recursive))
    show_filename = args.with_filename or len(files) > 1 or args.recursive
    any_match = False

    for label, text in files:
        matches = 0
        for lineno, line in enumerate(text.splitlines(), start=1):
            hit = bool(regex.search(line))
            if hit == (not args.invert_match):
                matches += 1
                any_match = True
                if args.count or args.files_with_matches:
                    continue
                prefix: list[str] = []
                if show_filename:
                    prefix.append(label)
                if args.line_number:
                    prefix.append(str(lineno))
                prefix.append(line)
                print(":".join(prefix))
        if args.files_with_matches and matches:
            print(label)
        elif args.count:
            print(f"{label}:{matches}" if show_filename else str(matches))

    sys.exit(0 if any_match else 1)


if __name__ == "__main__":
    main()
