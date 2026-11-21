# System

```bash
system/run <data folder> <output file>
```

It reads only the given data folder. Today it runs Stages 1–3, writes their artefacts to `working/` (or `$SANCTIONS_CACHE`), and writes a **run summary** to the output file. Stage 4, which writes one decision per hit, is not built yet.

| Folder | What it is | Doc |
|---|---|---|
| `stage1/` | Customer golden record | [docs/stage1-customer-golden-record.md](../docs/stage1-customer-golden-record.md) |
| `stage2/` | Hit golden profile | [docs/stage2-hit-golden-profile.md](../docs/stage2-hit-golden-profile.md) |
| `stage3/` | Alert → person resolution | [docs/stage3-alert-resolution.md](../docs/stage3-alert-resolution.md) |
| `shared/` | Name agreement, Stage 4 contracts, LLM client | [docs/shared-and-pipeline.md](../docs/shared-and-pipeline.md) |
| `pipeline.py`, `run` | Entry point | [docs/shared-and-pipeline.md](../docs/shared-and-pipeline.md) |
| `tests/` | Unit tests, synthetic fixtures | `cd system && python3 -m unittest discover -s tests` |

The submission README (architecture, how each side is resolved, evidence, determinism, model and prompts, time and cost, and three worked cases) will replace this file once Stage 4 writes decisions.
