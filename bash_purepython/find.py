"""PurePython implementation of the bash find command"""

# Standard libraries
import fnmatch
from argparse import ArgumentParser
from collections.abc import Iterator
from pathlib import Path

# Project libraries
from bash_purepython._color import print_error, print_warning

TYPE_FILE = "f"
TYPE_DIRECTORY = "d"
TYPE_SYMLINK = "l"


def walk(root: Path, max_depth: int | None) -> Iterator[tuple[Path, int]]:
    """Every path at or below root, paired with its depth

    Args:
        root: The file or directory to start from, reported at depth zero
        max_depth: The deepest level to descend to, or None to descend fully

    Returns:
        Pairs of path and depth, parents before their children
    """
    pending: list[tuple[Path, int]] = [(root, 0)]
    while pending:
        path, depth = pending.pop()
        yield path, depth

        if max_depth is not None and depth >= max_depth:
            continue
        if path.is_symlink() or not path.is_dir():
            continue

        try:
            children = sorted(path.iterdir(), reverse=True)
        except OSError as error:
            print_warning(f"find: {path}: {error.strerror}")
            continue
        pending.extend((child, depth + 1) for child in children)


def type_matches(path: Path, wanted: str | None) -> bool:
    """Whether the path is of the requested type

    Args:
        path: The path to test
        wanted: The -type letter, or None when no type was requested

    Returns:
        True when the path should be reported
    """
    if wanted is None:
        return True
    if wanted == TYPE_SYMLINK:
        return path.is_symlink()
    if wanted == TYPE_DIRECTORY:
        return path.is_dir()
    return path.is_file()


def name_matches(path: Path, pattern: str | None, ignore_case: bool) -> bool:
    """Whether the path's own name matches a glob

    Args:
        path: The path whose name is tested
        pattern: The glob to match, or None when no pattern was requested
        ignore_case: Whether the comparison folds case

    Returns:
        True when the name matches, or when no pattern was given
    """
    if pattern is None:
        return True
    if ignore_case:
        return fnmatch.fnmatch(path.name.lower(), pattern.lower())
    return fnmatch.fnmatchcase(path.name, pattern)


def main():
    parser = ArgumentParser(prog="find", description="Search for files in a directory hierarchy")
    parser.add_argument("paths", nargs="*", default=["."], help="Directories to search")
    parser.add_argument("-name", dest="name", help="Match the entry name against a glob pattern")
    parser.add_argument("-iname", dest="iname", help="Match the entry name against a case-insensitive glob")
    parser.add_argument(
        "-type",
        dest="type",
        choices=[TYPE_FILE, TYPE_DIRECTORY, TYPE_SYMLINK],
        help="Restrict results to files, directories, or symlinks",
    )
    parser.add_argument("-maxdepth", dest="max_depth", type=int, default=None, help="Deepest level to descend to")
    parser.add_argument("-mindepth", dest="min_depth", type=int, default=0, help="Shallowest level to report")

    args = parser.parse_args()

    if args.max_depth is not None and args.max_depth < 0:
        print_error("find: maxdepth must not be negative")
    if args.min_depth < 0:
        print_error("find: mindepth must not be negative")

    for path_str in args.paths:
        root = Path(path_str)
        if not root.exists():
            print_error(f"find: {path_str}: No such file or directory")

        for path, depth in walk(root, args.max_depth):
            if depth < args.min_depth:
                continue
            if not type_matches(path, args.type):
                continue
            if not name_matches(path, args.name, ignore_case=False):
                continue
            if not name_matches(path, args.iname, ignore_case=True):
                continue
            print(path)


if __name__ == "__main__":
    main()
