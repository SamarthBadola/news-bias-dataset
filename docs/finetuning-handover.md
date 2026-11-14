# Fine-tuning Handover

## Dataset and targets

Use `data/annotated/art_A1.jsonl` as the labeled source. It contains 165 rows: 155 marked `eval` and 10 marked `pilot`. Include all 165 rows in the current cross-validation plan, including the pilot items.

Fine-tune on two separate label targets:

| Axis | Labels and counts |
|---|---|
| Political | Left 37, Center 100, Right 28 |
| Gender | Misogynistic 18, Misandrist 18, Neutral 129 |

The communal/caste and cultural axes are `not_applicable` on all 165 single-article rows. Exclude these fields from fine-tuning targets during preprocessing; retain the source records unchanged. Those axes require matched article bundles and use a separate few-shot approach.

## Evaluation plan

Use five-fold cross-validation rather than a permanent train/validation/test split. In each outer fold, train on roughly 132 rows and evaluate on roughly 33; rotate folds so every row receives an out-of-fold prediction. Balance folds across both target axes as closely as possible. Keep known same-event or near-duplicate articles in the same fold where identifiable, and report actual per-fold class counts if grouping prevents perfect balance.

The smallest classes have only 18 examples each, so an individual test fold will contain about 3–4 examples of each non-neutral gender class. Pool out-of-fold predictions for per-class precision, recall and F1, alongside class counts, confusion matrices, macro-F1 and balanced accuracy. Treat rare-class metrics as uncertain; these targeted class proportions do not estimate real-world prevalence.

Fix the training settings before running outer evaluation. If tuning or checkpoint selection is needed, do it only within each outer training fold using inner cross-validation; never use that fold's held-out rows for tuning. Dropout and weight decay can help control overfitting, but they do not replace held-out predictions or increase the evidence available for evaluation.

After cross-validation, refit the chosen configuration on all 165 rows for the final model. Report the out-of-fold results as evaluation; do not present the final model's training scores as evaluation. This course-project estimate is intentionally modest and does not provide an independent external test set.

## Provenance and limitations

Candidates came from RSS feeds and targeted URLs, were fetched and screened for usable text, target outlet domains, duplicates and repeated event coverage, then labeled by A1 in Label Studio from the headline and lede with the outlet and URL hidden. Labels are human judgments guided by the annotation guideline. There is one annotator, so there is no inter-annotator agreement estimate. Targeted sourcing to improve gender-class coverage also means class proportions are not population estimates.

Check the current counts with:

```bash
python scripts/label_coverage.py data/annotated/art_A1.jsonl
python scripts/validate.py data/annotated/art_A1.jsonl
```
