# News Bias Dataset

This repository holds the data and tools for a hand-labeled evaluation set. The labels measure bias in Indian news headlines and their opening paragraphs across four axes: political ideology, gender bias, communal and caste bias, and cultural bias. The labeling rules are in [`docs/annotation-guideline.md`](docs/annotation-guideline.md). Read it before you label anything.

Keep this repository private. It stores short excerpts of articles that belong to their publishers.

## How an entry travels

```
RSS feeds ──collect.py──> data/raw/            articles as collected, never edited
                              │
                    make_stubs.py (maintainer only)
                              ▼
                       data/annotated/         one file per annotator, art_A1.jsonl and art_A2.jsonl
                              │
                 ls_tasks.py ─┴─> Label Studio ─> ls_import.py
                              │                   (labeling happens here, outlet hidden)
                              ▼
                  validate.py --promote        checks every entry, then copies finished ones
                              ▼
                        data/gold/             eval.jsonl, fewshot.jsonl, pilot.jsonl
```

`gold` and the split names are not two separate destinations. Each gold file is a split, and an entry goes to the file named in its own `split` field. Entries marked as overlap rows reach gold only when both annotators agree, or when they have discussed a disagreement and written down the outcome.

## Folders

| Path | What it holds | Who changes it |
|---|---|---|
| `data/raw/` | Collected articles, one file per day | Maintainer, through `collect.py` only |
| `data/annotated/` | Each annotator's working file | Annotators, through the scripts below |
| `data/gold/` | Finished entries, append-only | `validate.py --promote` only |
| `scripts/` | The tools | Through pull requests |
| `labelstudio/` | The Label Studio screen layout (`config.xml`) and temporary task files | Annotators |
| `docs/` | Guideline and an example entry | Through pull requests |
| `tests/` | Automated tests | Through pull requests |

Do not edit files in `raw/` or `gold/` by hand.

## Setup

You need Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate          # on Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m pytest                   # everything should pass before you start
```

Label Studio runs in Docker, so it needs no Python packages. Keep its data folder outside this repository so labels never end up in Git:

```bash
docker pull heartexlabs/label-studio:latest
docker run -it -p 8080:8080 -v "$HOME/ls-data:/label-studio/data" heartexlabs/label-studio:latest
```

Then open http://localhost:8080 and create a local account. Press Ctrl+C to stop it. Run the same command later to continue where you left off, because your projects live in `ls-data`. In PowerShell the same command works with `${HOME}` in place of `$HOME`. If port 8080 is busy, use `-p 8081:8080` and open port 8081 instead. On Linux, a permission error on the data folder usually means the folder needs to be owned by the container's user (`sudo chown -R 1001:root ~/ls-data`).

Docker only runs Label Studio. The Python scripts in this repository run on your own machine, in the virtual environment above. The two sides exchange files through your browser: you import a task file and export your labels.

If you prefer no Docker, `pip install label-studio` in a separate virtual environment and run `label-studio` also works.

The collector needs no API keys. Only `scripts/api_audit.py` reads keys, from a local `.env` file (copy `.env.example`). Never commit `.env`.

## Two rules that protect the labels

1. **Stay blind on axes 1 and 2.** Label from the headline and the opening paragraphs shown in Label Studio. Do not open the stub file in an editor while you label, and do not open the article. The URL and the outlet name are in the stub file on purpose, and seeing them would let reputation decide the label.
2. **Label alone.** Use your own Label Studio project. Do not discuss labels with the other annotator until both of you have finished the overlap rows.

## The maintainer's steps

One person runs these. Having one person do it means two annotators never get the same entry id.

```bash
git pull
python scripts/collect.py --limit 20            # first run: a small trial across many outlets
python scripts/inspect_raw.py --status ok --n 3 # read a few ledes before trusting the extraction
python scripts/inspect_raw.py                   # counts per outlet, plus every row that is not ok
python scripts/collect.py                       # full pull from rss_feeds.txt
python scripts/collect.py --url https://example.com/a-story    # one article that is not in any feed
python scripts/make_stubs.py --annotator A1 --n 40 --overlap 20 --pilot
python scripts/make_stubs.py --annotator A2 --n 20
python scripts/make_stubs.py --annotator A1 --n 6 --split fewshot   # few-shot exemplars for the LLM axes
python scripts/make_stubs.py --annotator A2 --clone data/annotated/art_A1.jsonl
git add data && git commit -m "data: add stubs for the pilot batch" && git push
```

Notes on those commands:

- `collect.py` reads robots.txt, spaces out its requests and retries temporary errors. It does not get around blocks or paywalls. A page it cannot read is saved with a status such as `robots_blocked` and is not annotated.
- `--no-fetch` shows what a run would collect and writes nothing. It also prints a per-feed table. A feed marked `<-- check this feed` returned nothing usable, so look at the list of off-target domains printed below it. If an outlet in that list belongs in the dataset, add its domain to `TARGETS` in `scripts/api_audit.py`.
- A feed that fails prints the reason, for example `network_error: ConnectionResetError`. Occasional failures are normal. A feed that fails every time usually means the site refuses automated clients. Leave such a site out instead of working around it.
- `--split` sets where finished entries land in gold: `eval` (the default) or `fewshot`. Pilot batches always go to `pilot`.
- `--pick URL` on `make_stubs.py` turns a specific collected article into a stub instead of sampling.
- `--clone` copies the first annotator's overlap rows into the second annotator's file. Only the text and the article facts are copied, never any labels, so both of you label identical text. Run it right after the first annotator's stubs exist.
- `make_stubs.py` limits how many stories about one event it samples (`--per-event-cap`, default 2, counting entries that already exist). It compares the names in headlines and opening paragraphs, and counts rarer names for more, so "Tiger Shroff" links stories while "Modi" alone does not. This is a review aid with a high threshold, not proof. After each run it lists pairs that look like the same story. Tag a deliberate group with `--event tiger-attack-2026-10`.
- To remove a stub (a recipe page, a third story about one event) run `python scripts/drop_stubs.py art-0008`. It edits every file in `data/annotated/`, refuses an id that is already in gold, and needs no quoting, so it works the same in PowerShell, Git Bash and cmd. Ids are never reused, so a gap in the numbering is normal.
- Pilot items (`--pilot`) also ask whether the standfirst alone would have given the same label. This tells us whether the platform can skip fetching article pages.

## The annotator's steps

Replace `A1` with your own id throughout.

1. **Pull.** `git pull`
2. **Build your task file.** It contains only an id, the headline and the opening paragraphs, shuffled in your own order.
   ```bash
   python scripts/ls_tasks.py --stubs data/annotated/art_A1.jsonl --out labelstudio/A1_tasks.json
   ```
3. **Set up Label Studio** (first time only). Start the Docker container and open http://localhost:8080. Create a project, then in its labeling setup choose a custom template, open the code view and paste the contents of `labelstudio/config.xml`. Menu names can differ slightly between Label Studio versions.
4. **Import** `labelstudio/A1_tasks.json` into the project.
5. **Label each task.** Follow the guideline.
   - Highlight the words that drove your decision. Use `political_evidence` or `gender_evidence` depending on the axis.
   - Pick the article type, the label and a confidence for each axis, and write a one-line rationale.
   - On pilot items, also answer the standfirst question.
6. **Export** from Label Studio in the full **JSON** format (not JSON-MIN or CSV). Your browser saves a file with a long generated name. Move it into the repo and rename it `labelstudio/A1_export.json`.
7. **Bring the labels back into your file.**
   ```bash
   python scripts/ls_import.py --export labelstudio/A1_export.json --stubs data/annotated/art_A1.jsonl --comparative not_applicable
   ```
   The `--comparative` option marks the communal/caste and cultural axes as not applicable. Use it only when none of your articles belongs to a comparison bundle (see the notes at the end). The script lists any task it could not use, for example a missing rationale or a highlighted phrase it could not find. Fix those in Label Studio, export again and rerun. A row that already has labels is skipped unless you add `--overwrite`.
8. **Validate.**
   ```bash
   python scripts/validate.py data/annotated/art_A1.jsonl
   ```
   It must end with `0 problems`. Some stubs still contain a `<placeholder>` you must replace by hand. The usual ones are `syndicated` and `original_source`, which appear when an agency name such as PTI or Bloomberg shows up in the text. Check the article page once the labeling is finished and replace them with `true` or `false` and the agency name or an empty string.
9. **Open a pull request** with your updated `data/annotated/art_A1.jsonl`.

### Promotion to gold (maintainer, after both annotators have pushed)

```bash
git pull
python scripts/validate.py data/annotated/art_A1.jsonl data/annotated/art_A2.jsonl --promote
git add data/gold && git commit -m "data: promote the pilot batch to gold" && git push
```

The script promotes nothing unless there are zero problems. After that:

- A row labeled by one annotator goes straight to `data/gold/<split>.jsonl`.
- An overlap row goes to gold when both files agree on every axis.
- An overlap row with a disagreement stays in `annotated/` and is listed. Discuss it, then add an `"adjudicated"` field to one of the two rows. Its labels become the final ones, and the note explains the decision, for example `"adjudicated": "Agreed Center: the headline quotes both sides."`. Both original labelings are kept in the gold entry under `annotations`.
- An id already in gold is skipped. If its content differs, the script stops with an error.

## What an entry looks like

[`docs/example-entry.json`](docs/example-entry.json) shows a finished entry. The fields fall into three groups:

| Group | Fields | Filled by |
|---|---|---|
| Collected facts | `id`, `url`, `published`, `outlet`, `title`, `standfirst`, `lede`, `retrieved_at`, `meta` | The scripts |
| Your judgments | `labels` (label, confidence, rationale, spans), `article_type`, `standfirst_sufficient` on pilot items | You, in Label Studio |
| Facts a person confirms | `syndicated`, `original_source`, `event_id`, `url_archive` | A person, when a placeholder asks |

`lede` is the first two body paragraphs after bylines and datelines are removed, cut to 120 words. `standfirst` is the feed's summary, cut to 40 words. Only entries with `lede_status` of `ok` are annotated. Other statuses mean the page gave no usable opening: `live_blog`, `too_short` (often a paywall), `fetch_failed`, `robots_blocked`, `extract_failed` or `domain_skipped`.

## How duplicates are prevented

| Where | What it catches |
|---|---|
| `collect.py` | An article already in `data/raw/` (same URL after removing `www`, trailing slashes, fragments and tracking parameters), or the same title from the same outlet |
| `make_stubs.py` | An article that already has a stub or a gold entry, the same wire story on another outlet (same opening words), and more stories about one event than `--per-event-cap` allows |
| `validate.py` | The same id or URL twice in a file, two ids for one article across annotator files and gold, and two ids with the same story text |

## Commit messages

Use the conventional prefixes:

| Prefix | Use for |
|---|---|
| `data:` | New or updated data files, such as `data: add art-0041 to art-0060 labels (A2)` |
| `feat:` | A new script or option |
| `fix:` | A bug fix or a corrected label, such as `fix(data): correct span in art-0007` |
| `docs:` | Guideline or README changes |
| `chore:` | Housekeeping |

## Troubleshooting

| You see | What it means and what to do |
|---|---|
| `'labels.political.label' is still a placeholder` | The entry has not been labeled yet. Run steps 5 to 7. |
| `highlighted text not found in title` | The phrase you highlighted spans a line break or was edited. Highlight it again in Label Studio, export and rerun. |
| `'lede' differs between ...` | The two annotators' files hold different text for the same id. Do not edit either file. Ask the maintainer to run `--clone` again. |
| `not promoted: ... waiting for the second annotator's file` | An overlap row. Pass both annotators' files to `validate.py`. |
| `nothing promoted: fix the problems above first` | Promotion is all or nothing. Fix every listed problem and rerun. |
| `lede_status: too_short` on many rows of one outlet | Often a paywall or a page of short briefs. Run `python scripts/inspect_raw.py --status too_short` and open one URL to see which. |
| `... are the same article URL` | Two different ids point at one article (links that differ only by tracking parameters count as the same). Keep one with `drop_stubs.py`. |
| `... are the same story text` | Two entries have the same opening words, which usually means one wire story on two outlets. Keep one. |
| A multi-line command pasted into PowerShell fails | PowerShell does not accept bash-style `<<EOF` blocks. Use the scripts in `scripts/`; they take plain arguments. |
| `trafilatura is not installed` | Run `pip install -r requirements.txt` inside your virtual environment. |

## Known gaps

- **Communal/caste and cultural bias (axes 3 and 4)** compare several articles, and the annotator needs the full article and its URL. The Label Studio screen covers axes 1 and 2 only, so these two axes are not labeled there yet. Until the bundle step exists, `--comparative` records single articles as not applicable.
- **Agreement statistics** (Cohen's kappa on the overlap rows) are not computed by any script yet.
- **Checking that a feed works.** Run `python scripts/collect.py --no-fetch` after editing `rss_feeds.txt`. It prints an error for every feed that fails and writes nothing.

## Tests

```bash
python -m pyflakes scripts tests
python -m pytest
```

GitHub runs both on every push.
