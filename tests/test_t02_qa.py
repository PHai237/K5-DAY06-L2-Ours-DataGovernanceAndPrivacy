"""QA & Testing Suite for T02 Raw QC Triage.

Owned by Member 4 (QA / Metric & Report).
Covers:
  1. Full End-to-End Pipeline Contract execution on real fixtures (fixtures/t02_raw_qc).
  2. Full Human-in-the-Loop review lifecycle (HOLD -> REWORK -> GO) and Audit Log tracking.
  3. Strict Provenance & Manifest Integrity verification (tamper / corruption rejection).
  4. Metric Fairness & Score Immutability Guard.
  5. Multi-Signal Scoring behavior & Failure Mode resilience (cam_B soft optics & local glare).
  6. Determinism & Offline reproducibility.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src import main as runner
from src.common.context import RunContext
from src.common.review import write_review_queue
from src.t02.scoring import extract_image_features, score_images


FIXTURE_DIR = Path("fixtures/t02_raw_qc")
CONFIG_PATH = Path("configs/lab.yaml")


# ---------------------------------------------------------------------------
# 1. Full E2E Pipeline Contract on Real Fixtures
# ---------------------------------------------------------------------------

def test_qa_full_pipeline_e2e_real_fixture(tmp_path: Path):
    """Verify that the official pipeline runs cleanly on actual fixtures via src.main."""
    out_dir = tmp_path / "poc_run"
    rc = runner.main([
        "--track", "t02",
        "--input", str(FIXTURE_DIR),
        "--config", str(CONFIG_PATH),
        "--output", str(out_dir),
        "--offline",
        "--seed", "42",
    ])
    assert rc == 0, f"Expected return code 0, got {rc}"

    # Verify all mandatory deliverables exist
    required_files = [
        "ranked_review.csv",
        "ranked_review_raw.csv",
        "review_queue.csv",
        "review_results.csv",
        "contact_sheet.html",
        "decision.json",
        "decision_log.csv",
        "audit_log.jsonl",
        "run_info.json",
    ]
    for fname in required_files:
        target = out_dir / fname
        assert target.is_file(), f"Missing required output file: {fname}"

    # Verify ranked output schema and completeness (all 96 images present)
    ranked = pd.read_csv(out_dir / "ranked_review.csv")
    assert len(ranked) == 96, f"Expected 96 ranked images, got {len(ranked)}"
    assert set(ranked.columns).issuperset({"image_id", "score", "pred_defect_type", "pred_action"})
    assert not ranked["score"].isna().any(), "Score column contains NaN"
    assert np.all(np.isfinite(ranked["score"].to_numpy())), "Score column contains Inf"

    # Verify review queue contains top B=20 images sorted descending by score
    queue = pd.read_csv(out_dir / "review_queue.csv")
    assert len(queue) == 20, f"Expected 20 items in review queue, got {len(queue)}"
    assert (queue["score"].diff().dropna() <= 1e-9).all(), "Review queue is not sorted descending by score"

    # Verify initial decision is HOLD because review is incomplete
    decision = json.loads((out_dir / "decision.json").read_text(encoding="utf-8"))
    assert decision["canonical"] == "HOLD"
    assert decision["reason_code"] == "REVIEW_INCOMPLETE"
    assert decision["metrics"]["queue_size"] == 20
    assert decision["metrics"]["n_pending"] == 20


# ---------------------------------------------------------------------------
# 2. Human-in-the-Loop Lifecycle & Audit Trail
# ---------------------------------------------------------------------------

def test_qa_human_review_transitions_rework_and_go(tmp_path: Path):
    """Verify human review decisions trigger correct governance states (REWORK vs GO)."""
    out_dir = tmp_path / "lifecycle_run"

    # Initial run to generate the initial queue
    runner.main([
        "--track", "t02",
        "--input", str(FIXTURE_DIR),
        "--config", str(CONFIG_PATH),
        "--output", str(out_dir),
        "--offline",
        "--seed", "42",
    ])

    q_file = out_dir / "review_queue.csv"
    assert q_file.exists()
    q = pd.read_csv(q_file, dtype=str).fillna("")

    # Scenario A: Reviewer marks one item as RECAPTURE -> should trigger REWORK
    q_rework = q.copy()
    q_rework["reviewer"] = "QA_Tester"
    q_rework["reviewer_decision"] = "approve"
    q_rework["review_note"] = "Standard verification pass"
    # Ensure at least one item has suggested_action RECAPTURE approved
    if not (q_rework["suggested_action"] == "RECAPTURE").any():
        q_rework.loc[0, "reviewer_decision"] = "edit"
        q_rework.loc[0, "override_value"] = "RECAPTURE"
        q_rework.loc[0, "review_note"] = "Manual override to RECAPTURE due to severe blur"

    reviewed_csv = out_dir / "review_queue_reviewed.csv"
    write_review_queue(q_rework, reviewed_csv)

    # Re-run pipeline to consume review_queue_reviewed.csv
    rc = runner.main([
        "--track", "t02",
        "--input", str(FIXTURE_DIR),
        "--config", str(CONFIG_PATH),
        "--output", str(out_dir),
        "--offline",
        "--seed", "42",
    ])
    assert rc == 0
    decision_rework = json.loads((out_dir / "decision.json").read_text(encoding="utf-8"))
    assert decision_rework["canonical"] == "REWORK"
    assert decision_rework["reason_code"] == "RECAPTURE_REQUIRED"

    # Scenario B: Reviewer approves or overrides ALL items as KEEP -> should trigger GO
    q_go = q.copy()
    q_go["reviewer"] = "QA_Lead"
    for idx in range(len(q_go)):
        if q_go.loc[idx, "suggested_action"] == "KEEP":
            q_go.loc[idx, "reviewer_decision"] = "approve"
            q_go.loc[idx, "review_note"] = "Confirmed clean"
        else:
            q_go.loc[idx, "reviewer_decision"] = "edit"
            q_go.loc[idx, "override_value"] = "KEEP"
            q_go.loc[idx, "review_note"] = "Defect is within acceptable tolerance"

    write_review_queue(q_go, reviewed_csv)
    rc = runner.main([
        "--track", "t02",
        "--input", str(FIXTURE_DIR),
        "--config", str(CONFIG_PATH),
        "--output", str(out_dir),
        "--offline",
        "--seed", "42",
    ])
    assert rc == 0
    decision_go = json.loads((out_dir / "decision.json").read_text(encoding="utf-8"))
    assert decision_go["canonical"] == "GO"
    assert decision_go["reason_code"] == "REVIEWED_QUEUE_KEEP"

    # Audit log validation
    audit_lines = (out_dir / "audit_log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(audit_lines) >= 20, "Audit log must contain audit events for queue reviews"
    audit_events = [json.loads(line) for line in audit_lines]
    actors = {e.get("actor") for e in audit_events}
    assert "QA_Lead" in actors or "QA_Tester" in actors


# ---------------------------------------------------------------------------
# 3. Strict Provenance & Manifest Integrity Edge Case
# ---------------------------------------------------------------------------

def test_qa_strict_provenance_tamper_detection(tmp_path: Path):
    """Verify that corrupting or tampering with fixture files triggers provenance failure."""
    from src import pipeline
    from src.common.io import load_config
    from src.common.context import RunContext

    # Copy fixture to a mutable temporary directory
    tampered_input = tmp_path / "tampered_fixture"
    shutil.copytree(FIXTURE_DIR, tampered_input)

    # Tamper with an image file by appending garbage bytes
    sample_img = next((tampered_input / "images").glob("*.jpg"))
    with open(sample_img, "ab") as f:
        f.write(b"CORRUPTED_BYTES_BY_QA")

    out_dir = tmp_path / "tamper_out"
    # 1. runner.main must catch ValueError and return exit code 2
    rc = runner.main([
        "--track", "t02",
        "--input", str(tampered_input),
        "--config", str(CONFIG_PATH),
        "--output", str(out_dir),
        "--offline",
    ])
    assert rc == 2

    # 2. pipeline.load must raise ValueError directly
    cfg = load_config(str(CONFIG_PATH))
    ctx = RunContext(
        track="t02",
        input_dir=tampered_input,
        output_dir=out_dir,
        config=cfg,
        seed=42,
        rng=np.random.default_rng(42),
    )
    with pytest.raises(ValueError, match="provenance check failed"):
        pipeline.load(ctx)


# ---------------------------------------------------------------------------
# 4. Metric Fairness: Score Immutability Guard
# ---------------------------------------------------------------------------

def test_qa_score_immutability_guard(tmp_path: Path, monkeypatch):
    """Verify that human review cannot modify model scores (preventing ranking manipulation)."""
    from src import pipeline
    from src.common.io import load_config
    from src.common.context import RunContext

    orig_review = pipeline.review

    def malicious_review(ctx, scored, queue):
        final_df, review_stats = orig_review(ctx, scored, queue)
        # Attempt to tamper with scores during review stage
        tampered_df = final_df.copy()
        tampered_df.loc[0, "score"] = 999.0
        return tampered_df, review_stats

    monkeypatch.setattr(pipeline, "review", malicious_review)
    out_dir = tmp_path / "cheat_out"

    # 1. runner.main must catch ValueError and return exit code 2
    rc = runner.main([
        "--track", "t02",
        "--input", str(FIXTURE_DIR),
        "--config", str(CONFIG_PATH),
        "--output", str(out_dir),
        "--offline",
    ])
    assert rc == 2

    # 2. Direct pipeline.run must raise ValueError
    cfg = load_config(str(CONFIG_PATH))
    ctx = RunContext(
        track="t02",
        input_dir=FIXTURE_DIR,
        output_dir=out_dir,
        config=cfg,
        seed=42,
        rng=np.random.default_rng(42),
    )
    with pytest.raises(ValueError, match="Human review must not change the ranking score"):
        pipeline.run(ctx)


# ---------------------------------------------------------------------------
# 5. Core Scoring Algorithm & Failure Mode Resilience
# ---------------------------------------------------------------------------

def test_qa_scoring_multi_signal_and_failure_modes():
    """Verify multi-signal feature extraction and failure mode resilience."""
    images = pd.read_csv(FIXTURE_DIR / "images.csv")
    ctx = RunContext(
        track="t02",
        input_dir=FIXTURE_DIR,
        output_dir=Path("out/test"),
        config={"track": "t02", "params": {"budget": 20, "dev_split": "dev"}},
        seed=42,
        rng=np.random.default_rng(42),
    )

    scored = score_images(ctx, images)
    assert len(scored) == len(images) == 96

    # Verify predicted defect types cover valid domain classes
    valid_defects = {"none", "blur", "glare", "dark", "compression"}
    unique_defects = set(scored["pred_defect_type"].unique())
    assert unique_defects.issubset(valid_defects)
    assert "none" in unique_defects
    assert "RECAPTURE" in set(scored["pred_action"].unique())
    assert "KEEP" in set(scored["pred_action"].unique())

    # Verify reasons are nonempty strings
    assert scored["reason"].str.len().min() > 5

    # Verification of T02 Failure Modes:
    # 1. Glare rescue: img_05_3 (eval, camera_A, dusk) has localized glare.
    #    Baseline (global Laplacian) misses it because overall sharpness is high (lap > 1300).
    #    PoC must flag it with a high score or glare defect.
    img_glare = scored[scored["image_id"] == "img_05_3"]
    assert not img_glare.empty
    assert img_glare["score"].iloc[0] > 1.0 or img_glare["pred_defect_type"].iloc[0] == "glare"

    # 2. Cam_B soft optics: img_06_0 (cam_B, clean) has naturally lower Laplacian.
    #    PoC should not push it to top-5 priority (contrast-normalized sharpness protects it).
    ranked = scored.sort_values("score", ascending=False).reset_index(drop=True)
    top_5_ids = set(ranked.head(5)["image_id"])
    assert "img_06_0" not in top_5_ids, "Clean cam_B image falsely ranked in top 5"


# ---------------------------------------------------------------------------
# 6. Offline & Determinism Reproducibility
# ---------------------------------------------------------------------------

def test_qa_determinism_across_runs(tmp_path: Path):
    """Verify deterministic ranking reproduction under seed 42."""
    out_1 = tmp_path / "run_1"
    out_2 = tmp_path / "run_2"

    runner.main([
        "--track", "t02",
        "--input", str(FIXTURE_DIR),
        "--config", str(CONFIG_PATH),
        "--output", str(out_1),
        "--offline",
        "--seed", "42",
    ])

    runner.main([
        "--track", "t02",
        "--input", str(FIXTURE_DIR),
        "--config", str(CONFIG_PATH),
        "--output", str(out_2),
        "--offline",
        "--seed", "42",
    ])

    df1 = pd.read_csv(out_1 / "ranked_review.csv")
    df2 = pd.read_csv(out_2 / "ranked_review.csv")

    pd.testing.assert_frame_equal(df1[["image_id", "score"]], df2[["image_id", "score"]])
