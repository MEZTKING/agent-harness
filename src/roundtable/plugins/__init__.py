"""Plugins: extra pieces anyone can add to Roundtable Hold (token saving, cost logs, tools...).

- ``api``: what a plugin can hook into (``API_VERSION``, ``Plugin``, ``PluginContext``)
- ``manifest``: ``roundtable-plugin.toml``, read and checked
- ``host``: loads the plugins that are on and calls their hooks, safely
- ``manage``: list, add, remove, switch on and off, trust, settings (the CLI and the app)
- ``sandbox``: each installed plugin in its own box (``boxworker`` the child, ``guard`` the
  rules, ``boxapi`` the API copy inside it)
- ``builtin``: ``token-saver`` and the example ``cost-log``

How to write one: docs/plugins.md.
"""
