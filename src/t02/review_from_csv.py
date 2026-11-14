"""Offline Leader review smoke test using an EXISTING predictions CSV.

This is NOT the PoC algorithm and does not compute any evaluation metric.
It reuses the exact same load/review/override/decision logic as the official
pipeline, allowing Leader to finish/test the human review while Core scoring
is being implemented separately.

    python -m src.main --config configs/t02_review_smoke.yaml \
      --pipeline src.t02.review_from_csv --output out/leader_smoke --offline

The source CSV must include every input image and at least image_id, score.
A source without pred_action will require reviewer's explicit KEEP/RECAPTURE
(edit) choices; it does not silently invent action labels.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .. import pipeline
from ..common.context import RunContext


def _read_scores(ctx: RunContext, data: dict) -> pd.DataFrame:
    raw_path = ctx.param("review_scores_csv")
    if not raw_path:
        raise ValueError("Set params.review_scores_csv in the chosen config for review-only mode")
    path = Path(str(raw_path))
    if "gt" in {part.lower() for part in path.parts}:
        raise ValueError("review_scores_csv may not point to ground truth (gt/)")
    if not path.is_file():
        raise FileNotFoundError(f"Review source predictions CSV not found: {path}")
    # Prevent accidentally reading/writing the same scored output file.
    for output in (ctx.output_dir / "ranked_review.csv", ctx.output_dir / "ranked_review_raw.csv"):
        if path.resolve() == output.resolve():
            raise ValueError("Review score source and output must be different files")
    frame = pd.read_csv(path, dtype={"image_id": str})
    ctx.stats["review_score_source"] = str(path)
    return frame


def run(ctx: RunContext) -> None:
    if ctx.track != "t02":
        raise NotImplementedError("review_from_csv only supports T02")
    print("[T02 Leader] REVIEW SMOKE ONLY — external predictions, not PoC metrics")
    pipeline.run(ctx, score_provider=_read_scores)
