"""Tests run offline: python -m pytest -q tests/test_t02_real_prepare.py"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tools.t02_real.prepare import prepare, read_csv, valid_qc_label, split_groups


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _make_root(tmp_path: Path, n: int = 10, *, duplicate: bool = False) -> Path:
    root = tmp_path / "traffic"
    root.mkdir()
    catalog, labels = [], []
    groups = ["blur", "glare", "dark", "poor_quality", "normal"]
    for i in range(n):
        category = groups[i % 5]
        ident = f"CASE_{i:03d}"
        rel = f"images/{category}/{ident}.jpg"
        image = root / rel
        image.parent.mkdir(parents=True, exist_ok=True)
        rng = np.random.default_rng(1000 + (0 if duplicate and i == 1 else i))
        Image.fromarray(rng.integers(0, 255, (220, 320, 3), dtype=np.uint8)).save(image, format="JPEG", quality=87)
        catalog.append({"image_id": ident, "category_candidate": category, "image_path": rel,
                        "file_title": f"Road traffic {ident}",
                        "source_page": f"https://commons.wikimedia.org/wiki/File:{ident}.jpg",
                        "license": "CC BY-SA 4.0", "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                        "dhash": "", "ahash": "", "width": "320", "height": "220", "quality_flag": "LIKELY_CUE"})
        is_defect = "0" if category == "normal" else "1"
        typ = "none" if category == "normal" else ("compression" if category == "poor_quality" else category)
        labels.append({"image_id": ident, "candidate_group": category, "review_status": "ACCEPT", "is_defect": is_defect,
                       "defect_type": typ, "severity": "0" if is_defect == "0" else "1", "reviewer": "test-reviewer", "notes": "", "scene_group": "group_shared" if i in (2, 3) else ""})
    _write_csv(root / "source_catalog.csv", catalog)
    _write_csv(root / "label_review.csv", labels)
    return root


def test_candidate_preparation_manifest_and_split(tmp_path):
    root = _make_root(tmp_path)
    report = prepare(root, expect=125)
    assert report["selected"] == 10
    assert report["target_met"] is False
    assert report["labels_verified"] is False
    ready = root / "ready"
    images = read_csv(ready / "images.csv")
    manifest = read_csv(ready / "manifest.csv")
    assert len(images) == 10
    assert len(manifest) == 11  # includes images.csv
    assert {i["split"] for i in images} == {"dev", "eval"}
    for m in manifest:
        assert hashlib.sha256((ready / m["path"]).read_bytes()).hexdigest() == m["sha256"]
    assert len(set(i["image_id"] for i in images)) == 10
    assert json.loads((ready / "real_dataset_card.json").read_text(encoding="utf-8"))["can_claim_official_metrics"] is False
    # Regenerating is reproducible; original catalog is untouched.
    csv_before = (ready / "images.csv").read_bytes()
    prepare(root, expect=125)
    assert (ready / "images.csv").read_bytes() == csv_before


def test_verified_requires_labels_and_reviewers(tmp_path):
    root = _make_root(tmp_path)
    rows = read_csv(root / "label_review.csv")
    rows[0]["review_status"] = "UNREVIEWED"
    rows[1]["reviewer"] = ""
    rows[2]["review_status"] = "REPLACE"
    _write_csv(root / "label_review.csv", rows)
    result = prepare(root, mode="verified")
    assert result["selected"] == 7
    assert result["labels_verified"] is True
    ids = {r["image_id"] for r in read_csv(root / "ready" / "images.csv")}
    assert ids.isdisjoint({"CASE_000", "CASE_001", "CASE_002"})


def test_duplicate_sha_rejected(tmp_path):
    root = _make_root(tmp_path, duplicate=True)
    result = prepare(root)
    assert result["selected"] == 9
    audit = read_csv(root / "ready" / "selection_audit.csv")
    assert any("duplicate_or_near_duplicate" in row["reason"] for row in audit)


def test_bad_sha_not_accepted(tmp_path):
    root = _make_root(tmp_path)
    cat = read_csv(root / "source_catalog.csv")
    cat[0]["sha256"] = "0" * 64
    _write_csv(root / "source_catalog.csv", cat)
    result = prepare(root)
    assert result["selected"] == 9
    assert any("sha256_mismatch" in r["reason"] for r in read_csv(root / "ready" / "selection_audit.csv"))


def test_verified_defect_consistency():
    r = {"review_status": "ACCEPT", "reviewer": "QA", "defect_type": "none", "is_defect": "0", "severity": "0"}
    assert valid_qc_label(r)
    assert not valid_qc_label({**r, "defect_type": "poor_quality"})
    assert not valid_qc_label({**r, "is_defect": "1"})
    assert not valid_qc_label({**r, "reviewer": ""})


def test_no_scene_group_split_leakage():
    rows = [{"scene_group": "same", "category_candidate": "blur"},
            {"scene_group": "same", "category_candidate": "dark"},
            {"scene_group": "other", "category_candidate": "normal"},
            {"scene_group": "third", "category_candidate": "normal"}]
    assigned = split_groups(rows, seed=42)
    assert assigned["same"] in {"dev", "eval"}
    assert len(set(assigned.values())) == 2


def test_split_is_exact_when_125_independent_photos():
    cats = ("blur", "glare", "dark", "poor_quality", "normal")
    data = [{"scene_group": f"scene_{i}", "category_candidate": cats[i % 5]} for i in range(125)]
    a = split_groups(data, seed=42)
    assert sum(x == "dev" for x in a.values()) == 75
    assert sum(x == "eval" for x in a.values()) == 50
    for cat in cats:
        assert sum(a[r["scene_group"]] == "dev" for r in data if r["category_candidate"] == cat) == 15
