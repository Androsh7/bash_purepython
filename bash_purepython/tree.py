"""PurePython implementation of the bash tree command"""

# Standard libraries
import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path

# Project libraries
from bash_purepython._color import print_error

BLANK = "    "
BOX_CHARACTERS = ("├── ", "└── ", "│   ")
ASCII_CHARACTERS = ("|-- ", "`-- ", "|   ")


def branch_characters() -> tuple[str, str, str]:
    """The branch, last branch and vertical strings stdout can encode

    Returns:
        The box drawing characters, or ASCII stand-ins on a narrow encoding
    """
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        "".join(BOX_CHARACTERS).encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return ASCII_CHARACTERS
    return BOX_CHARACTERS


def visible_children(directory: Path, show_all: bool, directories_only: bool) -> list[Path]:
    """The entries of a directory in display order

    Args:
        directory: The directory to list
        show_all: Whether entries whose name starts with a dot are included
        directories_only: Whether files are dropped from the listing

    Returns:
        The entries to print, sorted by name
    """
    entries = sorted(directory.iterdir(), key=lambda entry: entry.name)
    if not show_all:
        entries = [entry for entry in entries if not entry.name.startswith(".")]
    if directories_only:
        entries = [entry for entry in entries if entry.is_dir()]
    return entries


def render(directory: Path, prefix: str, depth: int, options: Namespace) -> tuple[int, int]:
    """Prints one level of the tree and everything below it

    Args:
        directory: The directory being listed
        prefix: The indentation inherited from the parent levels
        depth: How far below the starting point this directory sits
        options: The parsed command line options

    Returns:
        The number of directories and the number of files printed
    """
    if options.level is not None and depth >= options.level:
        return 0, 0

    try:
        entries = visible_children(directory, options.all, options.directories)
    except OSError as error:
        print(f"{prefix}[{error.strerror}]")
        return 0, 0

    branch, last_branch, vertical = options.charset

    directory_count = 0
    file_count = 0
    for index, entry in enumerate(entries):
        last = index == len(entries) - 1
        print(f"{prefix}{last_branch if last else branch}{entry.name}")

        if entry.is_dir() and not entry.is_symlink():
            directory_count += 1
            nested_directories, nested_files = render(entry, prefix + (BLANK if last else vertical), depth + 1, options)
            directory_count += nested_directories
            file_count += nested_files
        else:
            file_count += 1

    return directory_count, file_count


def main():
    parser = ArgumentParser(prog="tree", description="List the contents of directories as a tree")
    parser.add_argument("paths", nargs="*", default=["."], help="Directories to list")
    parser.add_argument("-a", "--all", action="store_true", help="Print entries whose name starts with a dot")
    parser.add_argument("-d", "--directories", action="store_true", help="Print directories only")
    parser.add_argument("-L", "--level", type=int, default=None, help="Deepest level to display")

    args = parser.parse_args()

    if args.level is not None and args.level < 1:
        print_error("tree: level must be at least 1")

    args.charset = branch_characters()

    total_directories = 0
    total_files = 0
    for path_str in args.paths:
        root = Path(path_str)
        if not root.exists():
            print_error(f"tree: {path_str}: No such file or directory")

        print(path_str)
        if root.is_dir():
            directories, files = render(root, "", 0, args)
            total_directories += directories
            total_files += files
        else:
            total_files += 1

    print()
    print(f"{total_directories} directories, {total_files} files")


if __name__ == "__main__":
    main()
