"""PurePython implementation of the bash ls command"""

# Standard libraries
from argparse import ArgumentParser
from pathlib import Path

# Project libraries
from bash_purepython._color import print_error

SIZE_UNITS = ("B", "K", "M", "G", "T", "P")
SIZE_UNIT_FACTOR = 1024


def collect_files(path_list: list[Path], recursive: bool) -> list[Path]:
    """Return every file named by the given paths

    Args:
        path_list: The files or directories to list
        recursive: Whether directories are walked all the way down

    Returns:
        The files found, in the order the paths were given
    """
    file_list: list[Path] = []
    for path in path_list:
        if recursive:
            file_list.extend(path.rglob("*"))
        else:
            file_list.extend(file_path for file_path in path.iterdir())
    return file_list


def format_size(size_bytes: int) -> str:
    """Return a byte count in the short form ls -lh uses, such as 4.0K or 12M

    Args:
        size_bytes: The size to format

    Returns:
        The size with a one-letter unit, one decimal below ten
    """
    size = float(size_bytes)
    for unit in SIZE_UNITS:
        if size < SIZE_UNIT_FACTOR or unit == SIZE_UNITS[-1]:
            if unit == "B":
                return f"{int(size)}"
            return f"{size:.1f}{unit}" if size < 10 else f"{size:.0f}{unit}"
        size /= SIZE_UNIT_FACTOR
    return f"{int(size_bytes)}"


def print_listing(file_list: list[Path], long: bool, human_readable: bool) -> None:
    """Write the listing to stdout

    Args:
        file_list: The files to print, already sorted
        long: Whether each file gets its own line with type and size
        human_readable: Whether sizes in the long listing use K, M and G
    """
    if long:
        for file_path in file_list:
            size = file_path.stat().st_size
            print(f"{'d' if file_path.is_dir() else 'f'} {format_size(size) if human_readable else size} {file_path}")
        return

    for file_path in file_list:
        print(str(file_path), end="  ")
    if file_list:
        print()


def main():
    """List the files at the given paths"""
    parser = ArgumentParser(prog="ls", description="List files in the given directory/directories", add_help=False)
    parser.add_argument("--help", action="help", help="Show this help message and exit")
    parser.add_argument("-l", "--long", action="store_true", help="Prints a long listing of files")
    parser.add_argument("-h", "--human-readable", action="store_true", help="With -l, print sizes like 1.5K or 12M")
    parser.add_argument("-a", "--all", action="store_true", help="Prints all files including hidden ones")
    parser.add_argument("-r", "--recursive", action="store_true", help="Prints all files recursively")
    parser.add_argument("paths", nargs="*", default=["."], help="Files or directories to list")

    args = parser.parse_args()

    # Validate the path list
    path_list = [Path(path_str) for path_str in args.paths]
    for path in path_list:
        if not path.exists():
            print_error(f"FileNotFound: {path}")

    file_list = collect_files(path_list, args.recursive)

    # Exclude "hidden" files if the all flag is not set
    if not args.all:
        file_list = [file_path for file_path in file_list if not file_path.name.startswith(".")]

    file_list.sort()
    print_listing(file_list, args.long, args.human_readable)


if __name__ == "__main__":
    main()
