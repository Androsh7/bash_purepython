"""PurePython implementation of the bash whoami command"""

# Standard libraries
import getpass
from argparse import ArgumentParser


def main():
    parser = ArgumentParser(prog="whoami", description="Print the current user name")
    parser.parse_args()
    print(getpass.getuser())


if __name__ == "__main__":
    main()
