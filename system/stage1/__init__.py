"""Stage 1: customer golden records (person_id).

Alert resolution is a later stage and is not implemented here.
"""

from stage1.build import build_from_tables, run_stage1

__all__ = ["build_from_tables", "run_stage1"]
