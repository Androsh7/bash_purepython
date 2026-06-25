"""PurePython implementation of the bash gzip command"""

# Standard libraries
import gzip as _gzip
import sys
from argparse import ArgumentParser
from pathlib import Path

# Project libraries
from bash_python_utils._color import print_error


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(prog="gzip", description="Compress or decompress files with gzip")
    parser.add_argument("-d", "--decompress", action="store_true", help="Decompress")
    parser.add_argument("-k", "--keep", action="store_true", help="Keep input files")
    parser.add_argument("-c", "--stdout", action="store_true", help="Write to stdout")
    parser.add_argument("-f", "--force", action="store_true", help="Overwrite existing output")
    parser.add_argument("-l", "--level", type=int, default=6, choices=range(1, 10), help="Compression level (1-9)")
    parser.add_argument("paths", nargs="+", help="Input files")
    return parser


def main(force_decompress: bool = False):
    args = build_parser().parse_args()
    decompress = args.decompress or force_decompress

    for path_str in args.paths:
        src = Path(path_str)
        if not src.exists():
            print_error(f"{src}: No such file or directory")
        if decompress:
            if src.suffix == ".gz":
                dst = src.with_suffix("")
            else:
                dst = src.with_suffix(src.suffix + ".out")
            data = _gzip.decompress(src.read_bytes())
        else:
            dst = src.with_suffix(src.suffix + ".gz")
            data = _gzip.compress(src.read_bytes(), compresslevel=args.level)

        if args.stdout:
            sys.stdout.buffer.write(data)
            continue
        if dst.exists() and not args.force:
            print_error(f"{dst}: already exists (use -f)")
        dst.write_bytes(data)
        if not args.keep:
            src.unlink()


if __name__ == "__main__":
    main()
