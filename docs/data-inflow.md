# Data Inflow and Class Coverage

The hand-labeled political and gender set is held out for evaluation. RSS supplies candidate articles; it does not supply their bias labels. Keep annotators blind to outlet and URL, and use only human labels for coverage counts.

## Build a broad candidate pool

Run a read-only feed check first, then collect a limited pool for review:

```powershell
python scripts/collect.py --no-fetch --limit 60
python scripts/collect.py --limit 60
python scripts/inspect_raw.py --status ok --n 3
python scripts/inspect_raw.py
```

The trial limit is distributed round-robin by feed and article domain so the first batch does not come only from the earliest large feed. The dry run applies the same limit as collection and reports, per feed, items read, eligible items, selected items, rejection reasons and, after collection, lede outcomes. `inspect_raw.py` summarizes the cumulative raw corpus by both host and source feed.

Use the existing national, politics and opinion feeds together. For topics underrepresented in the pool, prepare one-off article URLs or a URL list and collect them through `collect.py --url` or `--urls-file`. Political candidate topics can include elections, public policy, protests and government accountability. Gender candidate topics can include custody, crime reporting, workplace treatment and representation. These are search topics only; they do not predict an article's label.

Review extraction quality before making stubs. Keep only target-host articles with usable ledes. Retain source, topic and article type diversity; the stub sampler's per-domain cap helps prevent one outlet dominating. Do not use outlet reputation, section, a model prediction or a source's political leaning as an item's hand label.

## Track class coverage

Use the coverage report on each annotator file during annotation and on the resolved gold file before evaluation:

```powershell
python scripts/label_coverage.py --min-per-class 8 data/annotated/art_A1.jsonl data/annotated/art_A2.jsonl
python scripts/label_coverage.py --min-per-class 8 data/gold/eval.jsonl
```

The initial operational floor is 8 examples for each political class and each gender class. This is a coverage floor for the course MVP, not a claim of statistical precision. Aim for the existing 40 to 50 item cohort; after each labeled batch, source a targeted top-up for missing classes while preserving blind annotation. If a class remains below the floor at the agreed budget, report its count and treat its recall estimate as underpowered rather than changing labels or claiming full coverage. Report per-class recall and the confusion matrix; disclose class-targeted top-ups when interpreting overall accuracy or prevalence-sensitive metrics.

The first 10-row pilot remains a workflow check. It is too small and too skewed to serve as the final evaluation set. The two comparative axes need their own matched article bundles and should not count `not_applicable` single-article rows as class coverage.
