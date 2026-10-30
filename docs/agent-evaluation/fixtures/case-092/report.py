"""Intentionally incomplete seed: --output is not implemented."""
import argparse
import json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="world")
    args = parser.parse_args()
    print(json.dumps({"greeting": f"Hello, {args.name}!"}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
