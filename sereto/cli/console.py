from rich.console import Console as RichConsole

from sereto.singleton import Singleton


class Console(RichConsole, metaclass=Singleton):
    """Singleton wrapper around Rich's Console."""
