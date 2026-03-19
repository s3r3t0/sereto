import os
import shlex
from glob import iglob

import click
from click_repl import ClickCompleter  # type: ignore[import-untyped]
from prompt_toolkit.completion import Completion


class EscapedClickCompleter(ClickCompleter):
    """ClickCompleter that properly escapes path completions for shell safety."""

    def _get_completion_for_Path_types(
        self, param: click.Parameter, args: list[str], incomplete: str
    ) -> list[Completion]:
        if "*" in incomplete:
            return []

        choices: list[Completion] = []
        _incomplete = os.path.expandvars(incomplete)
        search_pattern = _incomplete.strip("'\"\t\n\r\v ").replace("\\\\", "\\") + "*"

        for path in iglob(search_pattern):
            escaped = shlex.quote(path)
            choices.append(
                Completion(
                    escaped,
                    -len(incomplete),
                    display=os.path.basename(path),
                )
            )

        return choices
