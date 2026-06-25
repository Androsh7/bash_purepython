"""PurePython implementation of the bash rm command"""

# Standard libraries
import shutil
from argparse import ArgumentParser
from pathlib import Path

# Project libraries
from bash_purepython._color import print_error


def main():
    parser = ArgumentParser(prog="rm", description="Remove files and directories")
    parser.add_argument("-r", "-R", "--recursive", action="store_true", help="Remove directories recursively")
    parser.add_argument("-f", "--force", action="store_true", help="Ignore missing files, never prompt")
    parser.add_argument("-d", "--dir", action="store_true", help="Remove empty directories")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print removed paths")
    parser.add_argument("paths", nargs="+", help="Paths to remove")
    args = parser.parse_args()

    for path_str in args.paths:
        path = Path(path_str)
        if not path.exists() and not path.is_symlink():
            if args.force:
                continue
            print_error(f"{path}: No such file or directory")
        if path.is_dir() and not path.is_symlink():
            if args.recursive:
                shutil.rmtree(path)
            elif args.dir:
                try:
                    path.rmdir()
                except OSError:
                    print_error(f"{path}: Directory not empty")
            else:
                print_error(f"{path}: is a directory (use -r or -d)")
        else:
            path.unlink()
        if args.verbose:
            print(f"removed {path}")


if __name__ == "__main__":
    main()
