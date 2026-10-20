"""JSON-lines CLI for rule inspection and external integrations."""

import argparse
import json
import sys

from . import evaluate


def main():
    parser = argparse.ArgumentParser(description="Evaluate a Python judge request.")
    parser.add_argument("game", choices=("snake", "msnake", "tank"))
    args = parser.parse_args()
    try:
        payload = json.loads(sys.stdin.readline())
        result = evaluate(args.game, payload)
        print(json.dumps(result, separators=(",", ":"), allow_nan=False))
    except (ValueError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
