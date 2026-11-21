"""Stage 3: resolve each screening alert to the customer person it is about.

This stage does not decide hits. It reads the Stage 1 record-level cache
(``record_view.jsonl`` and the ``index_*_record_id.json`` files) and writes
``alert_resolution.jsonl`` for Stage 4.
"""

from stage3.resolve import label_matches, resolve_alerts, summarise
from stage3.stage1_adapter import load_catalog

__all__ = ["label_matches", "load_catalog", "resolve_alerts", "summarise"]
