"""SeReTo TUI package.

Plugin integration
------------------
A plugin that wants to add a screen to the TUI defines a ``register_tui_actions``
function in its module alongside ``register_commands`` — the same file, the same
loading point.  SeReTo calls both when plugins are enabled in the global settings.

Plugin module convention::

    # my_plugin/__init__.py

    def register_commands(cli):
        cli.add_command(my_command)        # registers CLI subcommand

    def register_tui_actions(register_plugin):
        from my_plugin.tui_plugins import CspPlugin
        register_plugin(CspPlugin)          # registers TUI action button

:class:`TuiPlugin` subclass::

    from sereto.tui import TuiPlugin
    from my_plugin.screens import CspScreen

    class CspPlugin(TuiPlugin):
        label = "CSP Scan"        # button label — required
        screen = CspScreen        # Screen subclass to push — required
        # id = "csp"              # optional; defaults to lower-cased class name
        # requires_project = True # optional; default True
        # show_in_bar = True      # optional; default True
"""

from sereto.tui.app import TuiPlugin, launch_tui, register_tui_plugin

__all__ = ["TuiPlugin", "launch_tui", "register_tui_plugin"]
