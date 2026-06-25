"""PurePython implementation of the bash pwd command"""

# Standard libraries
from argparse import ArgumentParser
from pathlib import Path


def main():
    parser = ArgumentParser(prog="pwd", description="Print the current working directory")
    parser.parse_args()
    print(Path.cwd())


if __name__ == "__main__":
    main()
