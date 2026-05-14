# SPDX-License-Identifier: AGPL-3.0-only
"""Minimal Dagster :class:`~dagster.Definitions` for local Compose (Step 4 shell).

Replace or extend this module once :mod:`pipeline.factory` registers assets from
loaded definition repos (Step 6).
"""

from __future__ import annotations

from dagster import Definitions

defs = Definitions()
