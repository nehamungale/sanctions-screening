# Same Person or Not?

Public submission for the "Same Person or Not?" fin-crime hackathon (sanctions watchlist entity resolution). A bank's screening system has flagged possible matches between customers and watchlist profiles. For every hit, the system must decide whether the two records are the same person or company (`SAME_ENTITY`), clearly different (`DIFFERENT_ENTITY`), or still uncertain (`REVIEW`). Identity is the only question: whether the listing would still be acceptable to the bank is out of scope. The runnable system will live in `system/` and be invoked as `system/run <data folder> <output file>`.

## Layout

- `BRIEF.md` — the organisers' hackathon brief, copied verbatim.
- `POLICY.md` — the bank's identity SOP, copied verbatim.
- `output.schema.json` — JSON Schema for one output line, copied verbatim.
- `validate.py` — the organisers' validator and practice scorer, copied verbatim.
- `system/` — the runnable system. See `system/README.md`.
- `output/` — predictions. Development-set output will go to `output/dev.jsonl`.

## Data

The `dev/` dataset is for event participants only and is not committed. Place it locally at `./dev/` before running or validating.

## Validate

`validate.py` checks an output file the way the organisers do. `--data` is the data folder the output was made from (required), `--output` is the output file with one JSON line per hit (required), and `--score` is an optional path to `practice_labels.jsonl`.

```bash
python3 validate.py --data ./dev --output output/dev.jsonl
```

Score the practice hits as well:

```bash
python3 validate.py --data ./dev --output output/dev.jsonl --score ./dev/practice_labels.jsonl
```
