"""T02 Leader / Integration — the 5-stage official one-command pipeline.

Ownership convention to avoid merge conflicts:
  Member 1 (Leader): this file and src/t02/review_flow.py
  Member 2 (Baseline): src/t02/baseline.py (independent CLI pipeline)
  Member 3 (Core): src/t02/scoring.py::score_images(ctx, images)
  Member 4 (QA): tests/test_t02_qa.py + reports/ + demo/

Model code isn't bundled here: scoring.py starts as a clear NotImplementedError,
so starter test_cli still passes until member 3 merges their implementation.
"""
from __future__ import annotations

import pandas as pd

from .common.context import RunContext
from .common.decision import write_decision
from .common.manifest import verify_manifest
from .metrics.tracks import get_track
from .t02.review_flow import (
    apply_human_review, build_queue, decide_queue, normalise_predictions,
    validate_images,
)


def load(ctx: RunContext) -> dict:
    if ctx.track != "t02":
        raise NotImplementedError("Group solution currently implements T02 only")
    manifest = ctx.input_dir / "manifest.csv"
    if not manifest.is_file():
        raise FileNotFoundError(f"Missing manifest: {manifest}")
    problems = verify_manifest(manifest)
    if problems:
        if ctx.audit:
            ctx.audit.log(actor="pipeline", action="provenance_problems", item_id=str(manifest), after=problems[:20])
        if ctx.config.get("strict_provenance", True):
            raise ValueError(f"provenance check failed ({len(problems)} problems), first: {problems[:3]}")
    images = pd.read_csv(ctx.input_dir / "images.csv", dtype={"image_id": str, "path": str})
    return {"images": validate_images(ctx, images)}


def process(ctx: RunContext, data: dict) -> pd.DataFrame:
    """Model algorithm belongs to member 3; see src/t02/scoring.py."""
    from .t02.scoring import score_images
    return score_images(ctx, data["images"].copy())


def rank(ctx: RunContext, scored: pd.DataFrame) -> pd.DataFrame:
    return build_queue(ctx, scored)


def review(ctx: RunContext, scored: pd.DataFrame, queue: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    return apply_human_review(ctx, scored, queue)


def run(ctx: RunContext, score_provider=None) -> None:
    """Run the official five-step pipeline.

    ``score_provider`` is a Leader-only integration hook for testing a real
    review round-trip with existing model predictions while the Core member's
    ``score_images`` implementation is still in progress. Production calls
    use the default (Core) scoring function.
    """
    spec = get_track(ctx.track)
    if ctx.track != "t02":
        raise NotImplementedError("Implement the selected challenge in src/pipeline.py")
    data = load(ctx)                                 # 01 load + provenance
    scored = process(ctx, data) if score_provider is None else score_provider(ctx, data)  # 02
    scored = normalise_predictions(data["images"], scored)
    ctx.stats["n_items"] = len(scored)
    scored.to_csv(ctx.out("ranked_review_raw.csv"), index=False)
    queue = rank(ctx, scored)                        # 03 select B=20 + HTML
    final, review_stats = review(ctx, scored, queue) # 04 human override + audit
    ctx.stats.update(review_stats)
    # Model-generated score is immutable across the review stage (metric fairness).
    if not final["score"].equals(scored["score"]):
        raise ValueError("Human review must not change the ranking score")
    ordered = spec.pred_columns + [c for c in final.columns if c not in spec.pred_columns]
    final[ordered].to_csv(ctx.out(spec.pred_file), index=False)
    decision = decide_queue(ctx, queue, review_stats, final)  # 05 HOLD/GO/REWORK
    write_decision(decision, ctx.out("decision.json"), ctx.out("decision_log.csv"))
    if ctx.audit:
        ctx.audit.log(actor=decision.owner, action="batch_decision", item_id=decision.scope,
                      after=decision.canonical, reason=decision.reason,
                      reason_code=decision.reason_code)
