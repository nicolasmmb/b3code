"""python -m b3code"""

from b3code.container import AppContainer
from b3code.ui.app import B3App


def main() -> None:
    B3App(AppContainer.build()).run()


if __name__ == "__main__":
    main()
