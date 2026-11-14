"""Leader-owned T02 review/override/decision flow.

This module deliberately does not score images or read ground truth. It uses
built-in lab infrastructure and leaves core scoring to src/t02/scoring.py.

Outputs (out/):
  review_queue.csv           top-B suspicious images (B from config)
  contact_sheet.html         standalone offline browser review UI
  review_results.csv         reviewer input + effective KEEP/RECAPTURE
  audit_log.jsonl            append-only, from RunContext
  ranked_review_raw.csv      model predictions, before review
  ranked_review.csv          final predictions, score unchanged after review
  decision.json / decision_log.csv (written by src/pipeline.py)

Review export contract:
  Copy HTML's review_queue_reviewed.csv into the same output folder, re-run.
  'approve' accepts model action; 'edit'/'reject' require an explicit override
  KEEP/RECAPTURE plus a note; 'escalate' holds; 'skip' remains pending.

IMPORTANT: human overrides change ONLY pred_action, NEVER score, so official
Defect Recall@B evaluates unchanged automated ranking fairly.
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from ..common.contact_sheet import render_contact_sheet
from ..common.context import RunContext
from ..common.decision import Decision
from ..common.review import (
    apply_overrides,
    load_review_decisions,
    make_review_queue,
    write_review_queue,
)

ALLOWED_ACTIONS = {"KEEP", "RECAPTURE"}
REQUIRED_METADATA = ("image_id", "path", "camera_id", "light", "split")


def _check_relpath(input_dir: Path, raw_path: object) -> None:
    """Reject absolute paths, path traversal and hidden GT folder references."""
    p = Path(str(raw_path))
    if p.is_absolute() or not str(p) or str(p) == "nan":
        raise ValueError(f"Unsafe image path: {raw_path!r}")
    root = input_dir.resolve()
    target = (root / p).resolve()
    if not target.is_relative_to(root) or "gt" in target.relative_to(root).parts:
        raise ValueError(f"Unsafe image path: {raw_path!r}")
    if not target.is_file():
        raise FileNotFoundError(f"Missing image: {target}")


def validate_images(ctx: RunContext, images: pd.DataFrame) -> pd.DataFrame:
    """Check input metadata is safe before passing it to teammates' code."""
    missing = sorted(set(REQUIRED_METADATA) - set(images.columns))
    if missing:
        raise ValueError(f"images.csv missing columns: {missing}")
    if images.empty or images["image_id"].isna().any():
        raise ValueError("images.csv is empty or contains missing image_id")
    if images["image_id"].astype(str).duplicated().any():
        raise ValueError("images.csv contains duplicate image_id")
    for raw_path in images["path"]:
        _check_relpath(ctx.input_dir, raw_path)
    return images.copy()


def normalise_predictions(images: pd.DataFrame, scored: pd.DataFrame) -> pd.DataFrame:
    """Check complete one-to-one model output, and merge authoritative metadata.

    Ensures reviewer sees the actual source filename/light/camera. Numeric score
    is never silently filled or fabricated.
    """
    if not isinstance(scored, pd.DataFrame):
        raise ValueError("score_images must return a pandas DataFrame")
    needed = {"image_id", "score"}
    if not needed.issubset(scored.columns):
        raise ValueError(f"score_images missing required columns {sorted(needed - set(scored.columns))}")
    if scored.empty or scored["image_id"].isna().any():
        raise ValueError("Empty scoring output or missing image_id")
    scores = scored.copy()
    scores["image_id"] = scores["image_id"].astype(str)
    if scores["image_id"].duplicated().any():
        raise ValueError("Duplicate image_id in scoring output")
    scores["score"] = pd.to_numeric(scores["score"], errors="coerce")
    if not scores["score"].map(math.isfinite).all():
        raise ValueError("Every score must be a finite number")
    image_ids = set(images["image_id"].astype(str))
    score_ids = set(scores["image_id"])
    if image_ids != score_ids:
        raise ValueError(
            f"Scoring must cover the full input pool: missing={len(image_ids - score_ids)}, "
            f"unknown={len(score_ids - image_ids)}"
        )
    # Input metadata wins over model-created metadata, preventing mismatched paths.
    meta_cols = [x for x in REQUIRED_METADATA if x != "image_id"]
    scores = scores.drop(columns=[x for x in meta_cols if x in scores.columns])
    metadata = images[["image_id", *meta_cols]].copy()
    metadata["image_id"] = metadata["image_id"].astype(str)
    scores = scores.merge(metadata, on="image_id", how="left", validate="one_to_one")
    for c in ("pred_defect_type", "reason", "pred_action"):
        if c not in scores.columns:
            scores[c] = ""
        scores[c] = scores[c].fillna("").astype(str)
    scores["pred_action"] = scores["pred_action"].str.strip().str.upper()
    invalid = set(scores["pred_action"]) - (ALLOWED_ACTIONS | {""})
    if invalid:
        raise ValueError(f"Invalid pred_action {sorted(invalid)}; use KEEP, RECAPTURE or blank")
    # Stable ties: output always deterministic for identical model scores.
    return scores.sort_values("score", ascending=False, kind="mergesort").reset_index(drop=True)


def build_queue(ctx: RunContext, scored: pd.DataFrame) -> pd.DataFrame:
    budget = int(ctx.param("budget", 20))
    if budget < 1:
        raise ValueError("Review budget must be positive")
    q = make_review_queue(
        scored,
        id_col="image_id",
        score_col="score",
        budget=budget,
        reason_col="reason",
        action_col="pred_action",
        slice_col="light",
        evidence_col="path",
    )
    write_review_queue(q, ctx.out("review_queue.csv"))
    render_contact_sheet(
        q,
        ctx.out("contact_sheet.html"),
        image_root=ctx.input_dir,
        title=f"T02 Raw QC Triage — top {len(q)} images (offline)",
    )
    ctx.stats["review_budget"] = budget
    ctx.stats["queue_size"] = len(q)
    return q


def apply_human_review(ctx: RunContext, scored: pd.DataFrame, queue: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Apply reviewer decisions (only to selected queue items), with audit.

    Rejects unrecognised IDs, duplicates or invalid overrides. Input data must
    never be accepted as a source of numeric score overrides.
    """
    path = ctx.output_dir / "review_queue_reviewed.csv"
    reviewed = load_review_decisions(path) if path.exists() else pd.DataFrame()
    selected = set(queue["item_id"].astype(str))
    if not reviewed.empty:
        ids = reviewed["item_id"].astype(str)
        if ids.duplicated().any():
            raise ValueError("Duplicate reviewed item_id")
        unknown = set(ids) - selected
        if unknown:
            raise ValueError(f"Review file contains IDs outside top-B queue: {sorted(unknown)[:5]}")
        # Reject stale CSV exported from an older scoring run. Manual changes to
        # score/rank in the review file cannot silently modify the model output.
        current_queue = queue.set_index("item_id")
        for row in reviewed.itertuples(index=False):
            expected_rank = str(int(current_queue.loc[row.item_id, "rank"]))
            expected_score = float(current_queue.loc[row.item_id, "score"])
            try:
                submitted_score = float(row.score)
            except (TypeError, ValueError):
                raise ValueError(f"Bad score in reviewed CSV for {row.item_id}") from None
            if str(row.rank).strip() != expected_rank or not math.isclose(
                submitted_score, expected_score, rel_tol=0.0, abs_tol=0.000001
            ):
                raise ValueError(
                    f"Stale or modified review queue for {row.item_id}; export a new CSV from current contact sheet"
                )
        for row in reviewed.itertuples(index=False):
            dec = row.reviewer_decision
            action = str(row.override_value).strip().upper()
            if dec in {"edit", "reject"}:
                if action not in ALLOWED_ACTIONS:
                    raise ValueError(f"{dec} requires override_value KEEP/RECAPTURE for {row.item_id}")
                if not str(row.review_note).strip():
                    raise ValueError(f"{dec} requires a review_note (why?) for {row.item_id}")
            elif action:
                raise ValueError(f"{dec} must not supply override_value for {row.item_id}")
            if dec == "approve":
                current = scored.loc[scored.image_id == row.item_id, "pred_action"].iloc[0]
                if current not in ALLOWED_ACTIONS:
                    raise ValueError(f"Cannot approve missing prediction action for {row.item_id}; use edit")

    # Normalize override case before using common.review.apply_overrides.
    if not reviewed.empty:
        reviewed = reviewed.copy()
        reviewed["override_value"] = reviewed["override_value"].str.strip().str.upper()

    final = apply_overrides(scored, reviewed, "image_id", "pred_action", audit=ctx.audit)
    # Audit every reviewer decision, not just overrides. Append only, for traceability.
    if ctx.audit:
        for row in reviewed.itertuples(index=False):
            ctx.audit.log(
                actor=row.reviewer,
                action=f"review:{row.reviewer_decision}",
                item_id=row.item_id,
                before=row.suggested_action,
                after=final.loc[final.image_id == row.item_id, "pred_action"].iloc[0],
                reason=row.review_note,
            )

    resolved = set(reviewed.loc[reviewed.reviewer_decision.isin({"approve", "edit", "reject"}), "item_id"].astype(str)) if not reviewed.empty else set()
    skipped = set(reviewed.loc[reviewed.reviewer_decision == "skip", "item_id"].astype(str)) if not reviewed.empty else set()
    escalated = set(reviewed.loc[reviewed.reviewer_decision == "escalate", "item_id"].astype(str)) if not reviewed.empty else set()
    unresolved = selected - resolved
    effective = final.set_index("image_id")["pred_action"].to_dict()
    # Sidecar contains the complete selected queue, including still-pending items.
    review_results = queue.copy()
    if not reviewed.empty:
        columns = ["item_id", "reviewer", "reviewer_decision", "override_value", "review_note", "reviewed_at"]
        review_results = review_results.drop(columns=columns[1:]).merge(reviewed[columns], on="item_id", how="left", validate="one_to_one")
        for c in columns[1:]:
            review_results[c] = review_results[c].fillna("")
    review_results["final_action"] = review_results["item_id"].map(effective).fillna("")
    review_results.to_csv(ctx.out("review_results.csv"), index=False)
    stats = {
        "n_review_decisions": len(reviewed),
        "n_resolved": len(resolved),
        "n_pending": len(unresolved),
        "n_skipped": len(skipped),
        "n_escalated": len(escalated),
        "n_recapture_confirmed": sum(effective[i] == "RECAPTURE" for i in resolved),
    }
    return final, stats


def decide_queue(ctx: RunContext, queue: pd.DataFrame, review_stats: dict, final: pd.DataFrame) -> Decision:
    """Conservative *reviewed top-B queue* decision, not a claim about all images.

    HOLD for no/incomplete/escalated review; REWORK if a completely reviewed
    queue contains recapture actions; GO if all B reviewed and all KEEP.
    """
    pending = int(review_stats.get("n_pending", len(queue)))
    escalated = int(review_stats.get("n_escalated", 0))
    confirmed = int(review_stats.get("n_recapture_confirmed", 0))
    if escalated:
        status, code, reason = "HOLD", "REVIEW_ESCALATED", f"{escalated} image(s) escalated for specialist review"
    elif pending:
        status, code, reason = "HOLD", "REVIEW_INCOMPLETE", f"{pending}/{len(queue)} priority image(s) not resolved by human review"
    elif confirmed:
        status, code, reason = "REWORK", "RECAPTURE_REQUIRED", f"{confirmed} reviewed priority image(s) require recapture"
    else:
        status, code, reason = "GO", "REVIEWED_QUEUE_KEEP", "All reviewed priority images are KEEP (top-B queue only)"
    owner = str(ctx.config.get("owner", "")).strip()
    if not owner or owner.lower().startswith("todo"):
        raise ValueError("Set a real `owner` (review sign-off role/name) in configs/lab.yaml")
    return Decision(
        status=status,
        reason_code=code,
        reason=reason,
        owner=owner,
        scope=f"t02_top_{len(queue)}_review",
        evidence=[str(ctx.out("ranked_review.csv")), str(ctx.out("review_queue.csv")),
                  str(ctx.out("review_results.csv")), str(ctx.out("contact_sheet.html")),
                  str(ctx.out("audit_log.jsonl"))],
        metrics={"review_budget": int(ctx.param("budget", 20)),
                 "queue_size": len(queue), **review_stats},
    )
