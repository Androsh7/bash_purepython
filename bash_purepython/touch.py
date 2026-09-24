"""PurePython implementation of the bash touch command"""

# Standard libraries
import sys
from argparse import ArgumentParser
from pathlib import Path

# Project libraries
from bash_purepython._color import print_warning


def touch_path(path: Path, create: bool) -> bool:
    """Creates the file, or updates the timestamp of one that already exists

    Args:
        path: The file to touch
        create: Whether a file that does not exist yet is created

    Returns:
        True when the path was touched, False when it was reported as an error
    """
    if path.is_dir():
        print_warning(f"touch: {path}: Is a directory")
        return False

    if not create and not path.exists():
        return True

    try:
        path.touch(exist_ok=True)
    except OSError as error:
        print_warning(f"touch: {path}: {error.strerror}")
        return False
    return True


def main():
    parser = ArgumentParser(prog="touch", description="Create files or update their timestamps")
    parser.add_argument("-c", "--no-create", action="store_true", help="Do not create files that do not exist")
    parser.add_argument("-f", "--force", action="store_true", help="Accepted for compatibility and ignored")
    parser.add_argument("paths", nargs="+", help="Paths to create or update")

    args = parser.parse_args()

    failed = False
    for path_str in args.paths:
        if not touch_path(Path(path_str), create=not args.no_create):
            failed = True

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
