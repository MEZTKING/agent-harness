"""Kinds: what sort of thing a project makes, and the Gallery of finished work (docs/kinds.md).

The engine stays the same; a kind is a folder of data (model.py). The Gallery keeps one record per
finished goal (gallery.py)."""

from .model import (Catalog, Kind, KindError, apply_to_config, card, export, from_wizard, import_file,  # noqa: F401
                    load_all, overlay, plan_brief, proof_plan, propose, propose_extras, read_state, resolve,
                    status_of, status_words, validate, wizard_options, worker_brief)
