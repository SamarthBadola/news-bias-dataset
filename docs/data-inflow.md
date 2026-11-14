# Data Inflow and Class Coverage

The current corpus is the A1-only labeled set used for fine-tuning and cross-validation planning. RSS and targeted URLs supply candidate articles, not labels. Labels are assigned by one annotator from the article text, with outlet and URL hidden during Label Studio annotation.

## Build a broad candidate pool

Run a read-only feed check first, then collect a limited pool for review:

```powershell
python scripts/collect.py --no-fetch --limit 60
python scripts/collect.py --limit 60
python scripts/inspect_raw.py --status ok --n 3
python scripts/inspect_raw.py
```

The trial limit is distributed round-robin by feed and article domain so the first batch does not come only from the earliest large feed. The dry run applies the same limit as collection and reports, per feed, items read, eligible items, selected items, rejection reasons and, after collection, lede outcomes. `inspect_raw.py` summarizes the cumulative raw corpus by both host and source feed.

Use the existing national, politics and opinion feeds together. For topics underrepresented in the pool, prepare one-off article URLs or a URL list and collect them through `collect.py --url` or `--urls-file`. Political candidate topics can include elections, public policy, protests and government accountability. Gender candidate topics can include custody, crime reporting, workplace treatment and representation. These are search topics only; they do not predict an article's label. Targeted gender sourcing was used to improve rare-class coverage, so observed class proportions must not be reported as real-world prevalence.

Review extraction quality before making stubs. Keep only target-host articles with usable ledes. Retain source, topic and article type diversity; the stub sampler's per-domain cap helps prevent one outlet dominating. Do not use outlet reputation, section, a model prediction or a source's political leaning as an item's hand label.

## Track class coverage

Use the coverage report on the active A1 file during annotation and before model work:

```powershell
python scripts/label_coverage.py --min-per-class 8 data/annotated/art_A1.jsonl
```

The current 165-row A1 file contains political Left=37, Center=100, Right=28 and gender Misogynistic=18, Misandrist=18, Neutral=129. All 165 rows have communal/caste and cultural status `not_applicable`; those comparison axes have no class coverage in this single-article corpus. The script's floor of 8 is an operational coverage check, not a claim of statistical precision. Report per-class metrics and counts, and treat rare-class estimates as uncertain.

The 165-row snapshot includes 10 pilot rows and 155 rows marked `eval`. The agreed model evaluation plan uses all 165 in five-fold cross-validation, with the pilot rows retained. Balance folds across both fine-tuning axes and keep related event coverage together where identifiable. Fix training settings before evaluating; if tuning is needed, do it inside each outer training fold. See [`finetuning-handover.md`](finetuning-handover.md). The comparative axes need matched article bundles and must not count `not_applicable` single-article rows as class coverage.
