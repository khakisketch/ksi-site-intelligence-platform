"""Bounded local stdio MCP adapter for the KSI spatial-data AI boundary.

The adapter owns no device authority, no raster bytes, and no grant or
credential issuance. It calls the configured Core origin with an
operator-provisioned token and projects only Core-evidenced responses.
"""

from __future__ import annotations

__version__ = "0.0.1"
