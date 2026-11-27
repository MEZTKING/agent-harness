"""Plugins that come with Roundtable Hold (trusted; they can be switched off, not removed).

Each module has ``MANIFEST`` and ``make(cfg) -> (manifest, plugin object, enabled, settings)``.
The order here is the calling order: the token saver is always first.
"""

from . import attachments, compactor, cost_log, token_saver

BUILTINS = [token_saver.make, cost_log.make, compactor.make, attachments.make]
BUILTIN_MANIFESTS = {token_saver.MANIFEST.id: token_saver.MANIFEST, cost_log.MANIFEST.id: cost_log.MANIFEST,
                     compactor.MANIFEST.id: compactor.MANIFEST, attachments.MANIFEST.id: attachments.MANIFEST}
