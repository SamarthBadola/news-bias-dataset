# \# News Bias Dataset

# 

# This repository holds the data and tools for a hand-labeled evaluation set. The labels measure bias in Indian news headlines and their opening paragraphs across four axes: political ideology, gender bias, communal and caste bias, and cultural bias. The labeling rules are in \[`docs/annotation-guideline.md`](docs/annotation-guideline.md). Read it before you label anything.

# 

# Keep this repository private. It stores short excerpts of articles that belong to their publishers.

# 

# \## How an entry travels

# 

# ```

# RSS feeds ──collect.py──> data/raw/            articles as collected, never edited

# &#x20;                             │

# &#x20;                   make\_stubs.py (maintainer only)

# &#x20;                             ▼

# &#x20;                      data/annotated/         one file per annotator, art\_A1.jsonl and art\_A2.jsonl

# &#x20;                             │

# &#x20;                ls\_tasks.py ─┴─> Label Studio ─> ls\_import.py

# &#x20;                             │                   (labeling happens here, outlet hidden)

# &#x20;                             ▼

# &#x20;                 validate.py --promote        checks every entry, then copies finished ones

# &#x20;                             ▼

# &#x20;                       data/gold/             eval.jsonl, fewshot.jsonl, pilot.jsonl

# ```

# 

# `gold` and the split names are not two separate destinations. Each gold file is a split, and an entry goes to the file named in its own `split` field. Entries marked as overlap rows reach gold only when both annotators agree, or when they have discussed a disagreement and written down the outcome.

# 

# \## Folders

# 

# | Path | What it holds | Who changes it |

# |---|---|---|

# | `data/raw/` | Collected articles, one file per day | Maintainer, through `collect.py` only |

# | `data/annotated/` | Each annotator's working file | Annotators, through the scripts below |

# | `data/gold/` | Finished entries, append-only | `validate.py --promote` only |

# | `scripts/` | The tools | Through pull requests |

# | `labelstudio/` | The Label Studio screen layout (`config.xml`) and temporary task files | Annotators |

# | `docs/` | Guideline and an example entry | Through pull requests |

# | `tests/` | Automated tests | Through pull requests |

# 

# Do not edit files in `raw/` or `gold/` by hand.

# 

# \## Setup

# 

# You need Python 3.11 or newer.

# 

# ```bash

# python -m venv .venv

# source .venv/bin/activate          # on Windows: .venv\\Scripts\\activate

# pip install -r requirements-dev.txt

# python -m pytest                   # everything should pass before you start

# ```

# 

# Install Label Studio in its own environment, because it brings many packages with it:

# 

# ```bash

# python -m venv ls-venv

# source ls-venv/bin/activate        # on Windows: ls-venv\\Scripts\\activate

# pip install label-studio

# label-studio                       # opens http://localhost:8080

# ```

# 

# The collector needs no API keys. Only `scripts/api\_audit.py` reads keys, from a local `.env` file (copy `.env.example`). Never commit `.env`.

# 

# \## Two rules that protect the labels

# 

# 1\. \*\*Stay blind on axes 1 and 2.\*\* Label from the headline and the opening paragraphs shown in Label Studio. Do not open the stub file in an editor while you label, and do not open the article. The URL and the outlet name are in the stub file on purpose, and seeing them would let reputation decide the label.

# 2\. \*\*Label alone.\*\* Use your own Label Studio project. Do not discuss labels with the other annotator until both of you have finished the overlap rows.

# 

# \## The maintainer's steps

# 

# One person runs these. Having one person do it means two annotators never get the same entry id.

# 

# ```bash

# git pull

# python scripts/collect.py --limit 20            # first run: a small trial

# python scripts/collect.py                       # full pull from rss\_feeds.txt

# python scripts/collect.py --url https://example.com/a-story    # one article that is not in any feed

# python scripts/make\_stubs.py --annotator A1 --n 40 --overlap 20 --pilot

# python scripts/make\_stubs.py --annotator A2 --n 20

# python scripts/make\_stubs.py --annotator A1 --n 6 --split fewshot   # few-shot exemplars for the LLM axes

# python scripts/make\_stubs.py --annotator A2 --clone data/annotated/art\_A1.jsonl

# git add data \&\& git commit -m "data: add stubs for the pilot batch" \&\& git push

# ```

# 

# Notes on those commands:

# 

# \- `collect.py` reads robots.txt, spaces out its requests and retries temporary errors. It does not get around blocks or paywalls. A page it cannot read is saved with a status such as `robots\_blocked` and is not annotated.

# \- `--no-fetch` shows what a run would collect and writes nothing.

# \- `--split` sets where finished entries land in gold: `eval` (the default) or `fewshot`. Pilot batches always go to `pilot`.

# \- `--pick URL` on `make\_stubs.py` turns a specific collected article into a stub instead of sampling.

# \- `--clone` copies the first annotator's overlap rows into the second annotator's file. Only the text and the article facts are copied, never any labels, so both of you label identical text. Run it right after the first annotator's stubs exist.

# \- Pilot items (`--pilot`) also ask whether the standfirst alone would have given the same label. This tells us whether the platform can skip fetching article pages.

# 

# \## The annotator's steps

# 

# Replace `A1` with your own id throughout.

# 

# 1\. \*\*Pull.\*\* `git pull`

# 2\. \*\*Build your task file.\*\* It contains only an id, the headline and the opening paragraphs, shuffled in your own order.

# &#x20;  ```bash

# &#x20;  python scripts/ls\_tasks.py --stubs data/annotated/art\_A1.jsonl --out labelstudio/A1\_tasks.json

# &#x20;  ```

# 3\. \*\*Set up Label Studio\*\* (first time only). Start it, create a project, and open its labeling interface settings. Choose the code view and paste the contents of `labelstudio/config.xml`. Menu names can differ slightly between Label Studio versions.

# 4\. \*\*Import\*\* `labelstudio/A1\_tasks.json` into the project.

# 5\. \*\*Label each task.\*\* Follow the guideline.

# &#x20;  - Highlight the words that drove your decision. Use `political\_evidence` or `gender\_evidence` depending on the axis.

# &#x20;  - Pick the article type, the label and a confidence for each axis, and write a one-line rationale.

# &#x20;  - On pilot items, also answer the standfirst question.

# 6\. \*\*Export\*\* from Label Studio in the full \*\*JSON\*\* format (not JSON-MIN or CSV) and save it as `labelstudio/A1\_export.json`.

# 7\. \*\*Bring the labels back into your file.\*\*

# &#x20;  ```bash

# &#x20;  python scripts/ls\_import.py --export labelstudio/A1\_export.json --stubs data/annotated/art\_A1.jsonl --comparative not\_applicable

# &#x20;  ```

# &#x20;  The `--comparative` option marks the communal/caste and cultural axes as not applicable. Use it only when none of your articles belongs to a comparison bundle (see the notes at the end). The script lists any task it could not use, for example a missing rationale or a highlighted phrase it could not find. Fix those in Label Studio, export again and rerun. A row that already has labels is skipped unless you add `--overwrite`.

# 8\. \*\*Validate.\*\*

# &#x20;  ```bash

# &#x20;  python scripts/validate.py data/annotated/art\_A1.jsonl

# &#x20;  ```

# &#x20;  It must end with `0 problems`. Some stubs still contain a `<placeholder>` you must replace by hand. The usual ones are `syndicated` and `original\_source`, which appear when an agency name such as PTI or Bloomberg shows up in the text. Check the article page once the labeling is finished and replace them with `true` or `false` and the agency name or an empty string.

# 9\. \*\*Open a pull request\*\* with your updated `data/annotated/art\_A1.jsonl`.

# 

# \### Promotion to gold (maintainer, after both annotators have pushed)

# 

# ```bash

# git pull

# python scripts/validate.py data/annotated/art\_A1.jsonl data/annotated/art\_A2.jsonl --promote

# git add data/gold \&\& git commit -m "data: promote the pilot batch to gold" \&\& git push

# ```

# 

# The script promotes nothing unless there are zero problems. After that:

# 

# \- A row labeled by one annotator goes straight to `data/gold/<split>.jsonl`.

# \- An overlap row goes to gold when both files agree on every axis.

# \- An overlap row with a disagreement stays in `annotated/` and is listed. Discuss it, then add an `"adjudicated"` field to one of the two rows. Its labels become the final ones, and the note explains the decision, for example `"adjudicated": "Agreed Center: the headline quotes both sides."`. Both original labelings are kept in the gold entry under `annotations`.

# \- An id already in gold is skipped. If its content differs, the script stops with an error.

# 

# \## What an entry looks like

# 

# \[`docs/example-entry.json`](docs/example-entry.json) shows a finished entry. The fields fall into three groups:

# 

# | Group | Fields | Filled by |

# |---|---|---|

# | Collected facts | `id`, `url`, `published`, `outlet`, `title`, `standfirst`, `lede`, `retrieved\_at`, `meta` | The scripts |

# | Your judgments | `labels` (label, confidence, rationale, spans), `article\_type`, `standfirst\_sufficient` on pilot items | You, in Label Studio |

# | Facts a person confirms | `syndicated`, `original\_source`, `event\_id`, `url\_archive` | A person, when a placeholder asks |

# 

# `lede` is the first two body paragraphs after bylines and datelines are removed, cut to 120 words. `standfirst` is the feed's summary, cut to 40 words. Only entries with `lede\_status` of `ok` are annotated. Other statuses mean the page gave no usable opening: `live\_blog`, `too\_short` (often a paywall), `fetch\_failed`, `robots\_blocked`, `extract\_failed` or `domain\_skipped`.

# 

# \## Commit messages

# 

# Use the conventional prefixes:

# 

# | Prefix | Use for |

# |---|---|

# | `data:` | New or updated data files, such as `data: add art-0041 to art-0060 labels (A2)` |

# | `feat:` | A new script or option |

# | `fix:` | A bug fix or a corrected label, such as `fix(data): correct span in art-0007` |

# | `docs:` | Guideline or README changes |

# | `chore:` | Housekeeping |

# 

# \## Troubleshooting

# 

# | You see | What it means and what to do |

# |---|---|

# | `'labels.political.label' is still a placeholder` | The entry has not been labeled yet. Run steps 5 to 7. |

# | `highlighted text not found in title` | The phrase you highlighted spans a line break or was edited. Highlight it again in Label Studio, export and rerun. |

# | `'lede' differs between ...` | The two annotators' files hold different text for the same id. Do not edit either file. Ask the maintainer to run `--clone` again. |

# | `not promoted: ... waiting for the second annotator's file` | An overlap row. Pass both annotators' files to `validate.py`. |

# | `nothing promoted: fix the problems above first` | Promotion is all or nothing. Fix every listed problem and rerun. |

# | `trafilatura is not installed` | Run `pip install -r requirements.txt` inside your virtual environment. |

# 

# \## Known gaps

# 

# \- \*\*Communal/caste and cultural bias (axes 3 and 4)\*\* compare several articles, and the annotator needs the full article and its URL. The Label Studio screen covers axes 1 and 2 only, so these two axes are not labeled there yet. Until the bundle step exists, `--comparative` records single articles as not applicable.

# \- \*\*Agreement statistics\*\* (Cohen's kappa on the overlap rows) are not computed by any script yet.

# \- \*\*Checking that a feed works.\*\* Run `python scripts/collect.py --no-fetch` after editing `rss\_feeds.txt`. It prints an error for every feed that fails and writes nothing.

# 

# \## Tests

# 

# ```bash

# python -m pyflakes scripts tests

# python -m pytest

# ```

# 

# GitHub runs both on every push.

