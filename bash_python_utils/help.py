"""PurePython implementation of the bash help command"""

# Standard libraries
import pkgutil
from argparse import ArgumentParser

# Project libraries
import bash_python_utils


def main():
    parser = ArgumentParser(prog="help", description="Prints all commands")
    parser.parse_args()
    for _, name, _ in pkgutil.iter_modules(bash_python_utils.__path__):
        if name.startswith("_"):
            continue
        print(name, end="  ")
    print()


if __name__ == "__main__":
    main()
