"""PurePython implementation of the bash gunzip command"""

# Standard libraries
import sys

# Project libraries
from bash_purepython.gzip import main as gzip_main


def main():
    if "-d" not in sys.argv and "--decompress" not in sys.argv:
        sys.argv.insert(1, "-d")
    gzip_main()


if __name__ == "__main__":
    main()
