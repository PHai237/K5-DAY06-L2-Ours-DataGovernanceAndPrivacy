"""Team-owned tests for the Leader's T02 human review / integration.

These tests do not read ground truth and never fabricate official metric results.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from src import pipeline
from src.common.context import RunContext
from src.common.manifest import build_manifest, write_manifest
from src.common.review import AuditLog, write_review_queue
from src.t02.review_flow import normalise_predictions


def _make_ctx(tmp_path: Path, budget: int = 2) -> RunContext:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "out"
    (input_dir / "images").mkdir(parents=True)
    output_dir.mkdir()
    rows = []
    for idx in range(4):
        image_id = f"img_{idx:02d}"
        path = f"images/{image_id}.jpg"
        Image.new("RGB", (32, 20), (40 + 30 * idx, 80, 130)).save(input_dir / path)
        rows.append({"image_id": image_id, "path": path,
                     "camera_id": "cam_A", "light": "day", "split": "dev"})
    pd.DataFrame(rows).to_csv(input_dir / "images.csv", index=False)
    m = build_manifest(input_dir, ["images.csv", *(r["path"] for r in rows)],
                       source="synthetic:test", license="CC0")
    write_manifest(m, input_dir / "manifest.csv")
    return RunContext(track="t02", input_dir=input_dir, output_dir=output_dir,
                      config={"track": "t02", "owner": "T02 Team Lead",
                              "strict_provenance": True, "params": {"budget": budget}},
                      seed=42, rng=np.random.default_rng(42),
                      audit=AuditLog(output_dir / "audit_log.jsonl"))


def _fake_scores(ctx: RunContext, data: dict) -> pd.DataFrame:
    images = data["images"]
    return pd.DataFrame({
        "image_id": list(images.image_id),
        "score": [0.9, 0.8, 0.3, 0.1],
        "pred_action": ["RECAPTURE", "KEEP", "KEEP", "KEEP"],
        "pred_defect_type": ["blur", "none", "none", "none"],
        "reason": ["blur score high", "clean", "clean", "clean"],
    })


def test_leader_end_to_end_creates_queue_contact_sheet_and_hold(monkeypatch, tmp_path):
    ctx = _make_ctx(tmp_path)
    monkeypatch.setattr(pipeline, "process", _fake_scores)
    pipeline.run(ctx)
    for filename in ("review_queue.csv", "contact_sheet.html", "ranked_review.csv",
                     "ranked_review_raw.csv", "review_results.csv", "decision.json",
                     "decision_log.csv", "audit_log.jsonl"):
        assert (ctx.output_dir / filename).is_file(), filename
    q = pd.read_csv(ctx.output_dir / "review_queue.csv")
    assert len(q) == 2 and q.item_id.tolist() == ["img_00", "img_01"]
    assert q.evidence_path.str.startswith("images/").all()
    pred = pd.read_csv(ctx.output_dir / "ranked_review.csv")
    assert len(pred) == 4 and pred.columns[:2].tolist() == ["image_id", "score"]
    assert pred.score.tolist() == [0.9, 0.8, 0.3, 0.1]
    decision = json.loads((ctx.output_dir / "decision.json").read_text())
    assert (decision["status"], decision["reason_code"]) == ("HOLD", "REVIEW_INCOMPLETE")
    assert "data:image/jpeg;base64" in (ctx.output_dir / "contact_sheet.html").read_text()


def test_override_changes_only_action_and_produces_audited_go(monkeypatch, tmp_path):
    ctx = _make_ctx(tmp_path)
    monkeypatch.setattr(pipeline, "process", _fake_scores)
    pipeline.run(ctx)
    q = pd.read_csv(ctx.output_dir / "review_queue.csv", dtype=str).fillna("")
    q.loc[0, ["reviewer", "reviewer_decision", "override_value", "review_note"]] = [
        "Lead", "edit", "KEEP", "manual image inspection"
    ]
    q.loc[1, ["reviewer", "reviewer_decision", "review_note"]] = [
        "Lead", "approve", "looks good"
    ]
    write_review_queue(q, ctx.output_dir / "review_queue_reviewed.csv")
    pipeline.run(ctx)
    initial = pd.read_csv(ctx.output_dir / "ranked_review_raw.csv")
    final = pd.read_csv(ctx.output_dir / "ranked_review.csv")
    assert initial.score.equals(final.score)
    assert initial.pred_action.iloc[0] == "RECAPTURE"
    assert final.pred_action.iloc[0] == "KEEP"
    decision = json.loads((ctx.output_dir / "decision.json").read_text())
    assert decision["canonical"] == "GO"
    events = [json.loads(line) for line in (ctx.output_dir / "audit_log.jsonl").read_text().splitlines()]
    assert any(e["action"] == "override:edit" and e["item_id"] == "img_00" for e in events)
    assert any(e["action"] == "review:approve" and e["item_id"] == "img_01" for e in events)
    assert any(e["action"] == "batch_decision" and e["after"] == "GO" for e in events)


def test_complete_review_with_recapture_returns_rework(monkeypatch, tmp_path):
    ctx = _make_ctx(tmp_path)
    monkeypatch.setattr(pipeline, "process", _fake_scores)
    pipeline.run(ctx)
    q = pd.read_csv(ctx.output_dir / "review_queue.csv", dtype=str).fillna("")
    q.loc[:, "reviewer"] = "Lead"
    q.loc[:, "reviewer_decision"] = "approve"
    write_review_queue(q, ctx.output_dir / "review_queue_reviewed.csv")
    pipeline.run(ctx)
    decision = json.loads((ctx.output_dir / "decision.json").read_text())
    assert (decision["canonical"], decision["reason_code"]) == ("REWORK", "RECAPTURE_REQUIRED")


def test_unauthorised_item_override_is_rejected(monkeypatch, tmp_path):
    ctx = _make_ctx(tmp_path)
    monkeypatch.setattr(pipeline, "process", _fake_scores)
    pipeline.run(ctx)
    q = pd.read_csv(ctx.output_dir / "review_queue.csv", dtype=str).fillna("")
    q.loc[0, "item_id"] = "img_03"  # not in top-2
    q.loc[0, ["reviewer", "reviewer_decision", "override_value", "review_note"]] = [
        "Lead", "edit", "KEEP", "attempting unselected override"
    ]
    write_review_queue(q, ctx.output_dir / "review_queue_reviewed.csv")
    with pytest.raises(ValueError, match="outside top-B"):
        pipeline.run(ctx)


def test_override_without_reason_is_rejected(monkeypatch, tmp_path):
    ctx = _make_ctx(tmp_path)
    monkeypatch.setattr(pipeline, "process", _fake_scores)
    pipeline.run(ctx)
    q = pd.read_csv(ctx.output_dir / "review_queue.csv", dtype=str).fillna("")
    q.loc[0, ["reviewer", "reviewer_decision", "override_value"]] = [
        "Lead", "edit", "KEEP"
    ]
    write_review_queue(q, ctx.output_dir / "review_queue_reviewed.csv")
    with pytest.raises(ValueError, match="review_note"):
        pipeline.run(ctx)


def test_invalid_predictions_and_missing_pool_images_rejected(tmp_path):
    ctx = _make_ctx(tmp_path)
    images = pd.read_csv(ctx.input_dir / "images.csv")
    with pytest.raises(ValueError, match="finite"):
        normalise_predictions(images, pd.DataFrame({"image_id": images.image_id, "score": [1, float('nan'), 2, 3]}))
    with pytest.raises(ValueError, match="full input pool"):
        normalise_predictions(images, pd.DataFrame({"image_id": ["img_00"], "score": [0.1]}))
    with pytest.raises(ValueError, match="Invalid pred_action"):
        normalise_predictions(images, pd.DataFrame({"image_id": images.image_id,
                                                    "score": [0.1, 0.2, 0.3, 0.4],
                                                    "pred_action": ["KEEP", "DROP", "KEEP", "KEEP"]}))


def test_stale_review_csv_cannot_override_new_scores(monkeypatch, tmp_path):
    ctx = _make_ctx(tmp_path)
    monkeypatch.setattr(pipeline, "process", _fake_scores)
    pipeline.run(ctx)
    q = pd.read_csv(ctx.output_dir / "review_queue.csv", dtype=str).fillna("")
    q.loc[0, ["reviewer", "reviewer_decision", "override_value", "review_note"]] = [
        "Lead", "edit", "KEEP", "manual image inspection"
    ]
    q.loc[0, "score"] = "0.123456"
    write_review_queue(q, ctx.output_dir / "review_queue_reviewed.csv")
    with pytest.raises(ValueError, match="Stale or modified"):
        pipeline.run(ctx)


def test_review_csv_adapter_full_fixture_without_core_scoring(tmp_path, monkeypatch):
    """Review integration runs on all 96 fixture images without Core implementation."""
    from src.t02 import review_from_csv
    from src.common.io import load_config

    input_dir = Path("fixtures/t02_raw_qc")
    items = pd.read_csv(input_dir / "images.csv", dtype={"image_id": str})
    # Source data is deliberately UNLABELLED and not a benchmark prediction.
    # It only checks Leader plumbing against the full real fixture pool.
    samples = pd.DataFrame({"image_id": items.image_id,
                            "score": np.linspace(0, 1, len(items))})
    source = tmp_path / "scores.csv"
    samples.to_csv(source, index=False)
    cfg = load_config("configs/t02_review_smoke.yaml")
    cfg["params"]["review_scores_csv"] = str(source)
    out = tmp_path / "leader_out"
    ctx = RunContext(track="t02", input_dir=input_dir, output_dir=out, config=cfg,
                     seed=42, rng=np.random.default_rng(42),
                     audit=AuditLog(out / "audit_log.jsonl"))
    review_from_csv.run(ctx)
    assert len(pd.read_csv(out / "ranked_review.csv")) == 96
    queue = pd.read_csv(out / "review_queue.csv", dtype=str).fillna("")
    assert len(queue) == 20
    assert (out / "contact_sheet.html").exists()
    assert json.loads((out / "decision.json").read_text())["canonical"] == "HOLD"

    # An image without model action can still be edited by a reviewer.
    queue.loc[0, ["reviewer", "reviewer_decision", "override_value", "review_note"]] = [
        "Leader", "edit", "RECAPTURE", "Manual image inspection"
    ]
    write_review_queue(queue, out / "review_queue_reviewed.csv")
    review_from_csv.run(ctx)
    result = pd.read_csv(out / "ranked_review.csv")
    assert result.loc[result.image_id == queue.loc[0, "item_id"], "pred_action"].iloc[0] == "RECAPTURE"
    events = [json.loads(line) for line in (out / "audit_log.jsonl").read_text().splitlines()]
    assert any(x["action"] == "override:edit" for x in events)
    assert json.loads((out / "decision.json").read_text())["canonical"] == "HOLD"


def test_review_csv_adapter_rejects_missing_or_ground_truth_source(tmp_path):
    from src.t02.review_from_csv import _read_scores
    ctx = _make_ctx(tmp_path)
    ctx.config["params"]["review_scores_csv"] = str(tmp_path / "missing.csv")
    with pytest.raises(FileNotFoundError, match="not found"):
        _read_scores(ctx, {})
    ctx.config["params"]["review_scores_csv"] = "fixtures/t02_raw_qc/gt/labels.csv"
    with pytest.raises(ValueError, match="ground truth"):
        _read_scores(ctx, {})


def test_review_queue_rejects_stale_suggested_action(monkeypatch, tmp_path):
    ctx = _make_ctx(tmp_path)
    monkeypatch.setattr(pipeline, "process", _fake_scores)
    pipeline.run(ctx)
    q = pd.read_csv(ctx.output_dir / "review_queue.csv", dtype=str).fillna("")
    q.loc[0, ["reviewer", "reviewer_decision", "review_note"]] = [
        "Leader", "approve", "Reviewed"
    ]
    q.loc[0, "suggested_action"] = "KEEP"  # tampered/stale prediction
    write_review_queue(q, ctx.output_dir / "review_queue_reviewed.csv")
    with pytest.raises(ValueError, match="Stale or modified"):
        pipeline.run(ctx)
