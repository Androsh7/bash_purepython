"""PurePython implementation of the bash help command"""

# Standard libraries
from argparse import ArgumentParser

# Project libraries
from bash_purepython.shell.commands import list_command_names


def main():
    """Print the name of every command in the package"""
    parser = ArgumentParser(prog="help", description="Prints all commands")
    parser.parse_args()
    print("  ".join(list_command_names()))


if __name__ == "__main__":
    main()
