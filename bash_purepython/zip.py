"""PurePython implementation of the bash zip command"""

# Standard libraries
import zipfile
from argparse import ArgumentParser
from pathlib import Path

# Project libraries
from bash_python_utils._color import print_error


def main():
    parser = ArgumentParser(prog="zip", description="Create a zip archive")
    parser.add_argument("-r", "--recurse", action="store_true", help="Recurse into directories")
    parser.add_argument("-q", "--quiet", action="store_true", help="Quiet mode")
    parser.add_argument("-l", "--level", type=int, default=6, choices=range(0, 10), help="Compression level (0-9)")
    parser.add_argument("archive", help="Output zip archive")
    parser.add_argument("sources", nargs="+", help="Files or directories to add")
    args = parser.parse_args()

    compression = zipfile.ZIP_STORED if args.level == 0 else zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(args.archive, "w", compression=compression, compresslevel=args.level) as zf:
        for src_str in args.sources:
            src = Path(src_str)
            if not src.exists():
                print_error(f"{src}: No such file or directory")
            if src.is_dir():
                if not args.recurse:
                    print_error(f"{src}: is a directory (use -r)")
                for child in src.rglob("*"):
                    if child.is_file():
                        zf.write(child, child.relative_to(src.parent))
                        if not args.quiet:
                            print(f"adding: {child}")
            else:
                zf.write(src, src.name)
                if not args.quiet:
                    print(f"adding: {src}")


if __name__ == "__main__":
    main()
