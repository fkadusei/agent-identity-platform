"""Errors the simulators raise, so callers can tell them apart.

`NotFound` means the record does not exist — or exists for another tenant, which
is deliberately indistinguishable. Subclassing `ValueError` keeps every existing
`except ValueError` (and every test that asserts one) working, while the backend
seam can recognise *this* case and map it to the `None` a read returns — the same
thing the HTTP contract's 404 maps to.
"""
from __future__ import annotations


class NotFound(ValueError):
    """A record that is not there for this tenant."""
