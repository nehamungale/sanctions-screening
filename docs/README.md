# Docs

One doc per stage, plus one for the code they share. Each doc opens with a status table, ends with a **code map** and a **refactor plan**, and describes what is on `main` today. Refactor steps are marked *To do* until they land, then *Done* with the commit.

| Doc | Covers | Status |
|---|---|---|
| [stage1-customer-golden-record.md](stage1-customer-golden-record.md) | Customer side: cluster records into persons, pick verified facts, block flags, record views and indexes | Built |
| [stage2-hit-golden-profile.md](stage2-hit-golden-profile.md) | Watch-list side: names, countries, birth-date candidates, death, dated reports | Built |
| [stage3-alert-resolution.md](stage3-alert-resolution.md) | Which customer(s) each alert is about: links, joint accounts, name search | Built |
| [stage4-notes.md](stage4-notes.md) | Decision rules, alert roll-up, reasons and evidence | Built. As-built summary in [system/README.md](../system/README.md) |
| [shared-and-pipeline.md](shared-and-pipeline.md) | `system/run`, shared modules, LLM client, repro tool, tests, cross-stage refactor plan | Pipeline runs Stages 1–4 |
| [explainability-and-reproducibility.md](explainability-and-reproducibility.md) | Per-hit trace, reasons and citations, LLM rules, determinism, UI | Design. Trace written by Stage 4 |

The earlier review notes and the Stage 1 changelog were folded into these docs. Fixed items are described as current behaviour, and open items are in each doc's *Known gaps* or *Refactor plan*. The originals are in git history.

**Rules for every doc:** synthetic IDs and values only (never dev data), and the dev-run figures say which dataset they came from.
