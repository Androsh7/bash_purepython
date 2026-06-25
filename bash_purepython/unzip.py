"""PurePython implementation of the bash unzip command"""

# Standard libraries
import zipfile
from argparse import ArgumentParser
from pathlib import Path

# Project libraries
from bash_purepython._color import print_error


def main():
    parser = ArgumentParser(prog="unzip", description="Extract files from a zip archive")
    parser.add_argument("-d", "--directory", default=".", help="Extract into this directory")
    parser.add_argument("-l", "--list", action="store_true", help="List archive contents")
    parser.add_argument("-o", "--overwrite", action="store_true", help="Overwrite existing files")
    parser.add_argument("-q", "--quiet", action="store_true", help="Quiet mode")
    parser.add_argument("archive", help="Zip archive path")
    parser.add_argument("members", nargs="*", help="Members to extract (default all)")
    args = parser.parse_args()

    if not Path(args.archive).exists():
        print_error(f"{args.archive}: No such file or directory")

    with zipfile.ZipFile(args.archive) as zf:
        if args.list:
            for info in zf.infolist():
                print(f"{info.file_size:>10} {info.date_time} {info.filename}")
            return

        members = args.members or zf.namelist()
        target_dir = Path(args.directory)
        target_dir.mkdir(parents=True, exist_ok=True)
        for member in members:
            dest = target_dir / member
            if dest.exists() and not args.overwrite and not dest.is_dir():
                print_error(f"{dest}: already exists (use -o)")
            zf.extract(member, target_dir)
            if not args.quiet:
                print(f"extracted: {dest}")


if __name__ == "__main__":
    main()
