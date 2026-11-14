# T02 team integration contract — Day 06

**Purpose:** Small, reviewable Leader patch. No official scores are asserted. No
hidden labels are accessed, and no files under `fixtures/` are modified.

## Ownership to avoid merge conflicts

| Person | Owned files | Deliverable / interface |
|---|---|---|
| 1 — Leader | `src/pipeline.py`, `src/t02/review_flow.py`, `configs/lab.yaml` | Provenance load; queue B=20; offline HTML; reviewed CSV overrides; audit; GO/HOLD/REWORK; integration |
| 2 — Data/Baseline | `src/t02/baseline.py`, `reports/data_profile.md` | True single-threshold global Laplacian baseline using `laplacian_variance` on all 96 images; same B/seed; **does not modify pipeline.py** |
| 3 — Core Algorithm | `src/t02/scoring.py` | Implement `score_images(ctx, images)` returning **all 96** `image_id,score`, ideally `pred_defect_type,pred_action,reason`; **does not modify pipeline.py** |
| 4 — QA/Report | `tests/test_t02_qa.py`, `reports/*`, `demo/*` | ≥2 additional group tests; metric contract, baseline-vs-PoC, failure mode case studies, slides; **does not change scoring thresholds after eval** |

Only Leader edits `src/pipeline.py`. The QA member can add separate tests; the
Leader patch already includes regression tests in `tests/test_t02_leader.py`.
Everyone: meaningful commits with distinct `git config user.name/user.email`.

## Algorithm function contract for member 3

```python
# src/t02/scoring.py
import pandas as pd
from src.common.context import RunContext

def score_images(ctx: RunContext, images: pd.DataFrame) -> pd.DataFrame:
    # For each row, image path = ctx.input_dir / row.path
    # ctx.param("...") loads frozen thresholds; ctx.seed defaults to 42
    # Never read input_dir/gt or external network.
    # Return one row per image (NOT only eval or only top-20).
    return pd.DataFrame({
        "image_id": ...,                # str; exact match to images.csv, unique
        "score": ...,                   # finite float; higher = more suspicious
        "pred_defect_type": ...,        # optional: none/blur/glare/dark/compression
        "pred_action": ...,             # optional: KEEP or RECAPTURE
        "reason": ...,                  # optional short justification
    })
```

Do not manually assign fake evaluation labels in the algorithm. The official
metric uses an unseen `gt/` overlay; only `src.evaluate` can read GT.

## One-command run (once member 3 implemented the function)

Edit `configs/lab.yaml` first: `group_id` and `owner` must identify the real
team/reviewer. The configured owner must not be a TODO placeholder.

PowerShell (repo root):

```powershell
.\.venv\Scripts\python.exe -m tools.preflight
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m src.main --input fixtures/t02_raw_qc --config configs/lab.yaml --output out/poc --offline --seed 42
```

First run (without a reviewed CSV):

- `out/poc/ranked_review_raw.csv`: model-only complete ranking
- `out/poc/ranked_review.csv`: same scores, T02 official output
- `out/poc/review_queue.csv`: top-20, including source image paths
- `out/poc/contact_sheet.html`: standalone offline browser page
- `out/poc/review_results.csv`: review queue with final effective actions
- `out/poc/decision.json`, `decision_log.csv`, `audit_log.jsonl`: HOLD pending review, with owner/reasons

Open `out/poc/contact_sheet.html`, enter reviewer name, review rows, and click
**Export decisions CSV**. Move downloaded `review_queue_reviewed.csv` into
`out/poc/`, then run the **same `src.main` command** again.

* `approve`: accept model-suggested `pred_action`; the model must have output KEEP or RECAPTURE.
* `edit`/`reject`: provide **explicit** `override_value` KEEP or RECAPTURE and a nonempty `review_note`.
* `escalate`: requires specialist review → HOLD.
* `skip` or empty: not resolved → HOLD.

The reviewed CSV may only refer to the top-B item IDs; invalid/duplicate IDs
or invalid actions produce a clear error. Overrides change `pred_action` only.
**Scores never change**, preventing review leakage into Defect Recall@20.

Decision policy applies to the **reviewed top-B queue only**, not the entire
96-image dataset: incomplete review → HOLD; full review containing RECAPTURE →
REWORK; full review all KEEP → GO. Explicit evidence paths and reason_code are
attached to each decision; audit log appends a record on every run.

## Integration checklist

1. Member 2 provides own baseline module and dataset profiling; compare on the same full image pool and eval split, B=20, seed 42.
2. Member 3 replaces the `NotImplementedError` stub **only in** `src/t02/scoring.py`.
3. QA updates the original starter expectation in `tests/test_cli.py::test_template_pipeline_fails_clearly_not_silently`: after core is implemented it should test successful T02 output (exit code 0), rather than expecting starter exit code 3. Keep the negative test coverage with a separate invalid input test.
4. Leader updates `configs/lab.yaml` (`owner`, `group_id`, freeze thresholds), merges PRs, verifies `preflight`, `pytest`, `src.main --offline --seed 42`, reviews 20 images, attaches audit / report / slides.
5. Hidden evaluation is **not** available in student repo. Do not make up Defect Recall@20, Precision@20 or type accuracy. Record unavailable with a transparent explanation; run `src.evaluate` only when provided with legitimate GT.

## Other notes

- The shipped `src/examples/random_baseline.py` is a seeded random wiring demo. T02.md separately specifies a **global Laplacian threshold baseline**; the team must implement that, not relabel random as Laplacian.
- `configs/lab.yaml` defaults to `owner: TODO...` and `group_id: G00`. The Leader must set real values before running the completed end-to-end pipeline.
- The prior `.gitattributes` fix `fixtures/** -text` should already be on the team's `main`; this patch does not replace it.
- Do not stage `.venv/`, `out/`, `data/real/`, hidden GT or private files. Keep actual reviewer data and evidence only as allowed by course policy.

## Leader smoke test — RUN NOW without Member 3's algorithm

This uses the **official random example** for unlabelled review interface input.
It is **not** a Laplacian baseline, a valid defect prediction or an official
metric. It exercises the Leader's actual I/O, HTML, overrides, audit, gate
on the full 96-image fixture without asking Member 3 to finish first.

Use PowerShell, from the repository root:

```powershell
# 1) Produce a reproducible *sample* score CSV (NO ground truth access).
.\.venv\Scripts\python.exe -m src.main --track t02 --pipeline src.examples.random_baseline --config configs/t02_review_smoke.yaml --output out/leader_fixture_scores --run-name leader-smoke-scores --offline --seed 42

# 2) Feed those score rows into the REAL Leader's review + audit + gate.
.\.venv\Scripts\python.exe -m src.main --track t02 --pipeline src.t02.review_from_csv --config configs/t02_review_smoke.yaml --output out/leader_smoke --run-name leader-smoke --offline --seed 42

# 3) Open the offline HTML to review the selected 20 images.
Start-Process .\out\leader_smoke\contact_sheet.html
```

Random example contains no `pred_action`, therefore **approve is not valid**
for those rows. Use **edit + KEEP/RECAPTURE + review_note**, or use a real
scoring CSV from Member 3 with suggested action. Export the CSV from the HTML
and copy `review_queue_reviewed.csv` into `out/leader_smoke/`, then re-run
command #2. Expected before full review: `HOLD/REVIEW_INCOMPLETE` with audit
entries for edited items. No changes are made to the `fixtures/` tree.

For real end-to-end PoC, use the ordinary official `src.pipeline` once
Member 3 finishes; **never** use review_from_csv as the submission pipeline.
