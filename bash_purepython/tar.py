"""PurePython implementation of the bash tar command"""

# Standard libraries
import tarfile
from argparse import ArgumentParser
from pathlib import Path

# Project libraries
from bash_python_utils._color import print_error


def main():
    parser = ArgumentParser(prog="tar", description="Create, extract, or list tar archives")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("-c", "--create", action="store_true", help="Create a new archive")
    mode.add_argument("-x", "--extract", action="store_true", help="Extract files from an archive")
    mode.add_argument("-t", "--list", action="store_true", help="List archive contents")
    parser.add_argument("-f", "--file", required=True, help="Archive path")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("-z", "--gzip", action="store_true", help="Use gzip compression")
    parser.add_argument("-j", "--bzip2", action="store_true", help="Use bzip2 compression")
    parser.add_argument("-J", "--xz", action="store_true", help="Use xz compression")
    parser.add_argument("-C", "--directory", default=None, help="Change to directory before operating")
    parser.add_argument("members", nargs="*", help="Files to add or members to extract")
    args = parser.parse_args()

    compression = ""
    if args.gzip:
        compression = "gz"
    elif args.bzip2:
        compression = "bz2"
    elif args.xz:
        compression = "xz"

    if args.create:
        mode_str = f"w:{compression}" if compression else "w"
        with tarfile.open(args.file, mode_str) as tf:
            for member in args.members:
                arcname = member
                target = Path(args.directory) / member if args.directory else Path(member)
                if not target.exists():
                    print_error(f"{target}: No such file or directory")
                if args.verbose:
                    print(arcname)
                tf.add(target, arcname=arcname)
    elif args.extract:
        mode_str = f"r:{compression}" if compression else "r:*"
        with tarfile.open(args.file, mode_str) as tf:
            members = tf.getmembers() if not args.members else [tf.getmember(m) for m in args.members]
            for m in members:
                if args.verbose:
                    print(m.name)
            tf.extractall(args.directory or ".", members=members, filter="data")
    elif args.list:
        mode_str = f"r:{compression}" if compression else "r:*"
        with tarfile.open(args.file, mode_str) as tf:
            for m in tf.getmembers():
                print(m.name)


if __name__ == "__main__":
    main()
