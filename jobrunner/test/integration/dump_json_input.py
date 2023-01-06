#!/usr/bin/env python3

from json import dump, load
from os import environ
from sys import stdin


def main():
    data = load(stdin)
    with open(environ["DUMP_FILE"], "w", encoding="utf-8") as fp:
        dump(data, fp, indent=2)
    print("dumped")


if __name__ == "__main__":
    main()
