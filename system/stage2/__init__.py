"""Stage 2: hit golden profiles (hit_id).

Alert resolution and the decision rules are later stages and are not
implemented here.
"""

from stage2.build import build_profiles, run_stage2

__all__ = ["build_profiles", "run_stage2"]
