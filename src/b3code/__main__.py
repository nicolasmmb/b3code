"""python -m b3code"""

import argparse
import sys

from b3code.container import AppContainer
from b3code.ui.app import B3App


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="b3code")
    parser.add_argument(
        "--session",
        nargs="?",
        const=None,
        default=None,
        metavar="ID",
        help="resume a session by id; without a value, start a new session",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    container = AppContainer.build()
    try:
        container.session_store.start(args.session)
    except ValueError as exc:
        print(f"b3code: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    B3App(container).run()


if __name__ == "__main__":
    main()
