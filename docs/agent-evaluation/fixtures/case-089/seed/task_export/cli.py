import argparse
import json
from .repository import load_tasks


def main():
    parser = argparse.ArgumentParser(description="List tasks from a JSON file")
    parser.add_argument("input", help="UTF-8 JSON file containing tasks")
    args = parser.parse_args()
    print(json.dumps(load_tasks(args.input), ensure_ascii=False))
