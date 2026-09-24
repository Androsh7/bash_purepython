"""PurePython implementation of the bash ls command"""

# Standard libraries
from argparse import ArgumentParser
from pathlib import Path

# Project libraries
from bash_purepython._color import print_error


def collect_files(path_list: list[Path], recursive: bool) -> list[Path]:
    """Every file named by the given paths

    Args:
        path_list: The files or directories to list
        recursive: Whether directories are walked all the way down

    Returns:
        The files found, in the order the paths were given
    """
    file_list: list[Path] = []
    for path in path_list:
        if recursive:
            file_list.extend(path.rglob("*", recurse_symlinks=False))
        else:
            file_list.extend(file_path for file_path in path.iterdir())
    return file_list


def print_listing(file_list: list[Path], long: bool) -> None:
    """Writes the listing to stdout

    Args:
        file_list: The files to print, already sorted
        long: Whether each file gets its own line with type and size
    """
    if long:
        for file_path in file_list:
            print(f"{'d' if file_path.is_dir() else 'f'} {file_path.stat().st_size} {file_path}")
        return

    for file_path in file_list:
        print(str(file_path), end="  ")
    if file_list:
        print()


def main():
    parser = ArgumentParser(prog="ls", description="List files in the given directory/directories")
    parser.add_argument("-l", "--long", action="store_true", help="Prints a long listing of files")
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
    print_listing(file_list, args.long)


if __name__ == "__main__":
    main()
