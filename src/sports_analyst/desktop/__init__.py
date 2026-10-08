"""Desktop entry point, with native UI imports deferred until launch."""


def main() -> None:
    from sports_analyst.desktop.app import main as launch

    launch()
