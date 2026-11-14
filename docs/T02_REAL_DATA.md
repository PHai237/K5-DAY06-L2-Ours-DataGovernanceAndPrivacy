# T02 — Run the Core PoC on real traffic photos (local-only)

This adapter is deliberately **not** a change to `configs/lab.yaml` or the synthetic fixture. It prepares a second T02 input folder while maintaining source hashes and real-photo attributions. It does **not** claim photographs are correctly categorized or that candidate folders are ground truth.

## 0. Requirements

- Already downloaded traffic photos under `data/real/t02_traffic_125/` using `fetch_traffic_125.py` from `data/t02-traffic-tooling`.
- `source_catalog.csv`, original `images/<category>/*.jpg` and `label_review.csv` remain in that folder.
- `configs/lab.yaml` has a real `owner` (for example `Pham Hai (Leader / Review Sign-off)`, without `TODO`).
- Run at repo root with the repo's existing `.venv`.
- No upload/commit of real photos, contact sheets containing real photos, or labels to public GitHub.

## 1. Optional: try to finish the missing 5 glare candidates

Only if the collector is already present in `tools/t02_data/`:

```powershell
.\.venv\Scripts\python.exe .\tools\t02_data\fetch_traffic_125.py --out .\data\real\t02_traffic_125 --per-group 25 --pause 2.5
```

The existing 120 stay in place. Missing 5 **does not prevent** a provisional 120-image demonstration. `--skip-seeds` is omitted intentionally, so previously skipped seed candidates can be retried. Don't hammer Commons after HTTP 429; respect its rate limits.

## 2. Prepare T02 data from the real photographs

```powershell
.\.venv\Scripts\python.exe -m tools.t02_real.prepare --root .\data\real\t02_traffic_125 --mode candidate
```

This creates `data/real/t02_traffic_125/ready/` with:

- `images/`: local copies of candidate photos, not synthetic artwork;
- `images.csv`: unique image IDs, paths, `split` assigned reproducibly with seed 42 (roughly 60/40), `camera_id` and `light` are `unknown` unless manually provided;
- `manifest.csv`: SHA-256 for every image and for `images.csv`; original Commons source/license preserved;
- `selection_audit.csv`: accepted/excluded records and reasons (including hash/near-duplicate failures and missing metadata);
- `attribution.csv`: original photo titles, authors, Commons pages and licenses;
- `real_dataset_card.json`: real counts and explicit provenance limitations.

The adapter does **not** train on real eval labels and does not modify `fixtures/t02_raw_qc/` or the original collection. It does not infer image category by looking at a picture; source `blur`/`glare`/etc remains **unverified candidate metadata**. Some views of the same traffic event may not be detected as related scenes; TV4 must fill `scene_group` in `label_review.csv` where necessary and rerun prepare before relying on the split.

The generated `ready/` can be recreated. The collector's source files are not modified.

## 3. One-command Windows run (recommended)

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\t02_real\run_real_t02.ps1
```

Optionally add `-Collect` to try again for the 5 missing glare candidates. Once TV4 verifies the labels, use `-Mode verified`. A run that still has 120 candidates is supported; it will be reported as 120, not as 125.

### Equivalent individual commands: Check manifest and run Core + Leader on real photos

```powershell
.\.venv\Scripts\python.exe -c "from src.common.manifest import verify_manifest; from pathlib import Path; p=Path('data/real/t02_traffic_125/ready/manifest.csv'); e=verify_manifest(p); print('Manifest:', 'PASS' if not e else e[:5]); assert not e"
.\.venv\Scripts\python.exe -m src.main --track t02 --config configs/lab.yaml --input data/real/t02_traffic_125/ready --output out/poc_real --offline --seed 42
Get-Content .\out\poc_real\decision.json -Encoding utf8
Start-Process .\out\poc_real\contact_sheet.html
```

Expect `status=0`. First decision is normally `HOLD / REVIEW_INCOMPLETE` because no human has reviewed the Top 20 yet. A successful run means **the pipeline executed**, not that the defects were classified correctly.

**Important:** The real-data contact sheet is for local viewing only. After a scoring/config/dataset change, don't reuse previously exported `review_queue_reviewed.csv`; export again from the new contact sheet to avoid stale-queue rejection. Review actions are `approve`, `edit`, `reject` or `escalate`; overrides require an explanation.

## 4. Switch to human-verified set (TV4 responsibility)

TV4 checks all images in the source `contact_sheet.html` and edits `data/real/t02_traffic_125/label_review.csv` for each selected picture:

- `review_status=ACCEPT` or `VERIFIED` only after viewing the image; use `REPLACE` to exclude bad photos.
- For each accepted image: `reviewer`, `is_defect` (`0/1`), `defect_type` (`none/blur/glare/dark/compression`) and `severity` (`0/1/2`) with consistent values.
- For actual same-scene images, optional new column `scene_group` should contain the same value, ensuring the same split. Unreviewed values are **never** accepted as ground truth.
- `poor_quality` is **not** a valid T02 defect type: choose a real supported type or reject.
- Optional `light` column can be filled `day/dusk/night` by a human; never invent a camera ID.

Then:

```powershell
.\.venv\Scripts\python.exe -m tools.t02_real.prepare --root .\data\real\t02_traffic_125 --mode verified
.\.venv\Scripts\python.exe -m src.main --track t02 --config configs/lab.yaml --input data/real/t02_traffic_125/ready --output out/poc_real_verified --offline --seed 42
```

Check `real_dataset_card.json` for actual retained counts, and export/review the fresh Top 20. Locally verified QC labels are **not** the instructor's hidden GT. Avoid claiming official `Defect Recall@20` on these images; define a separate local-real evaluation protocol if useful.

## 5. Report wording

> "We preserved the 96 synthetic fixture images as the reproducible instructor evaluation input. Separately, we ran a real-traffic-photo out-of-domain demonstration using a dataset sourced from Wikimedia Commons. We checked SHA-256 and metadata provenance, removed detected duplicates, assigned a reproducible dev/eval split and generated an offline Top-20 human-review sheet. The image categories from the collector were provisional; no official recall/precision claim was made without confirmed QC labels."

**Limits:** Filename search and low-level image features do not prove that the subject is road traffic or that photo defects are severe. This step needs TV4 validation. Only compare metrics after labels/protocol are verified and splits frozen. Keep photos and labels under `data/real/` (already gitignored).
