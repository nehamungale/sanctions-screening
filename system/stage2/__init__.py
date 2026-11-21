"""Stage 2: hit golden profiles (hit_id).

Stage 3 resolves alerts. Stage 4 will decide hits. Neither lives in this package.
"""

from stage2.build import build_profiles, run_stage2

__all__ = ["build_profiles", "run_stage2"]
