"""PurePython implementation of the bash mv command"""

# Standard libraries
import shutil
from argparse import ArgumentParser
from pathlib import Path

# Project libraries
from bash_python_utils._color import print_error


def main():
    parser = ArgumentParser(prog="mv", description="Move or rename files and directories")
    parser.add_argument("-f", "--force", action="store_true", help="Overwrite existing destinations")
    parser.add_argument("-n", "--no-clobber", action="store_true", help="Do not overwrite existing files")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print moved paths")
    parser.add_argument("sources", nargs="+", help="Source paths")
    parser.add_argument("dest", help="Destination path")
    args = parser.parse_args()

    dest = Path(args.dest)
    multi_source = len(args.sources) > 1
    if multi_source and not dest.is_dir():
        print_error(f"target {dest} is not a directory")

    for src_str in args.sources:
        src = Path(src_str)
        if not src.exists():
            print_error(f"{src}: No such file or directory")
        target = dest / src.name if dest.is_dir() else dest
        if target.exists():
            if args.no_clobber:
                continue
            if not args.force:
                print_error(f"{target} already exists (use -f to overwrite)")
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        shutil.move(str(src), str(target))
        if args.verbose:
            print(f"{src} -> {target}")


if __name__ == "__main__":
    main()
