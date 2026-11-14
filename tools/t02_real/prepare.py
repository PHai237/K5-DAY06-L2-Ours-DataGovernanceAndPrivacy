"""Prepare verified provenance and dev/eval partitions for local T02 traffic photos.

Input:  data/real/t02_traffic_125/ produced by tools/t02_data/fetch_traffic_125.py.
Output: <input>/ready/ (local-only, gitignored); NEVER overwrites collector input.

Candidate mode is for demo/integration ONLY, not ground truth / official evaluation.
Verified mode requires explicit, independently checked human QC labels.

Use: python -m tools.t02_real.prepare --root data/real/t02_traffic_125
     python -m tools.t02_real.prepare --root data/real/t02_traffic_125 --mode verified
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, UnidentifiedImageError

CATEGORIES = ("blur", "glare", "dark", "poor_quality", "normal")
DEFECT_TYPES = {"none", "blur", "glare", "dark", "compression"}
IMAGE_COLUMNS = ["image_id", "path", "camera_id", "light", "split"]
MANIFEST_COLUMNS = ["file_id", "path", "source", "license", "split", "group_id", "sha256"]
REVIEW_COLUMNS = ["image_id", "candidate_group", "review_status", "is_defect", "defect_type", "severity", "reviewer", "notes", "source_page", "quality_flag", "scene_group", "reason"]
ALLOWED_LICENSE_HINTS = ("cc0", "public domain", "cc by", "cc-by", "creative commons")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_path(root: Path, raw: str) -> Path:
    rel = Path(str(raw))
    if rel.is_absolute() or not rel.parts or rel.parts[0] != "images" or ".." in rel.parts:
        raise ValueError(f"Unsafe image path: {raw!r}")
    actual = (root / rel).resolve()
    if not actual.is_relative_to(root.resolve()):
        raise ValueError(f"Image escapes source root: {raw!r}")
    return actual


def valid_qc_label(row: dict) -> bool:
    status = str(row.get("review_status", "")).strip().upper()
    if status not in {"ACCEPT", "VERIFIED", "REVIEWED"} or not str(row.get("reviewer", "")).strip():
        return False
    defect = str(row.get("defect_type", "")).strip().lower()
    is_defect = str(row.get("is_defect", "")).strip()
    severity = str(row.get("severity", "")).strip()
    return (defect in DEFECT_TYPES and is_defect in {"0", "1"}
            and severity in {"0", "1", "2"}
            and (defect == "none") == (is_defect == "0")
            and (severity == "0") == (is_defect == "0"))


def _hash_bits(x: str, y: str) -> int:
    try:
        return (int(x, 16) ^ int(y, 16)).bit_count() if x and y else 64
    except (ValueError, TypeError):
        return 64


def _near_duplicate(a: dict, b: dict) -> bool:
    try:
        ar = float(a.get("width") or 0) / float(a.get("height") or 0)
        br = float(b.get("width") or 0) / float(b.get("height") or 0)
        ratio_close = ar > 0 and br > 0 and abs(ar / br - 1) < 0.055
    except (ValueError, ZeroDivisionError):
        ratio_close = False
    return (ratio_close and _hash_bits(a.get("dhash", ""), b.get("dhash", "")) <= 5
            and _hash_bits(a.get("ahash", ""), b.get("ahash", "")) <= 7)


def _stable_order(group: str, seed: int) -> str:
    return hashlib.sha256(f"{seed}:{group}".encode("utf-8")).hexdigest()


def split_groups(items: list[dict], seed: int = 42, dev_ratio: float = 0.60) -> dict[str, str]:
    """Stable category-stratified 60/40 target, keeping manually declared scenes together.

    Counts are exact when every group contains one image and a matching integer
    target exists. Larger scene groups are indivisible and may change totals.
    """
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in items:
        grouped[row["scene_group"]].append(row)
    cat_n = Counter(row["category_candidate"] for row in items)
    cat_target = {cat: round(n * dev_ratio) for cat, n in cat_n.items()}
    total_target = round(len(items) * dev_ratio)
    units_by_cat: dict[str, list[str]] = defaultdict(list)
    for group, members in grouped.items():
        sub = Counter(x["category_candidate"] for x in members)
        major = sorted(sub, key=lambda c: (-sub[c], c))[0]
        units_by_cat[major].append(group)
    assigned: dict[str, str] = {}
    dev_by_cat: Counter = Counter()
    for cat in sorted(units_by_cat):
        for group in sorted(units_by_cat[cat], key=lambda g: _stable_order(g, seed)):
            sub = Counter(x["category_candidate"] for x in grouped[group])
            before = sum(abs(dev_by_cat[c] - cat_target[c]) for c in cat_target)
            after = sum(abs(dev_by_cat[c] + sub[c] - cat_target[c]) for c in cat_target)
            choice = "dev" if after < before else "eval"
            assigned[group] = choice
            if choice == "dev":
                dev_by_cat.update(sub)
    def dev_size() -> int:
        return sum(len(grouped[g]) for g, split in assigned.items() if split == "dev")
    # Rebalance toward the global exact count without ever splitting a scene.
    for _ in range(len(grouped)):
        now = dev_size()
        if now == total_target:
            break
        want = "eval" if now < total_target else "dev"
        proposals = []
        for group, split in assigned.items():
            if split != want:
                continue
            size = len(grouped[group])
            new = now + size if want == "eval" else now - size
            if abs(new - total_target) >= abs(now - total_target):
                continue
            sub = Counter(x["category_candidate"] for x in grouped[group])
            current_error = sum(abs(dev_by_cat[c] - cat_target[c]) for c in cat_target)
            new_error = sum(abs(dev_by_cat[c] + (sub[c] if want == "eval" else -sub[c]) - cat_target[c]) for c in cat_target)
            proposals.append((abs(new - total_target), new_error - current_error, _stable_order(group, seed), group))
        if not proposals:
            break
        _, _, _, group = min(proposals)
        new_split = "dev" if assigned[group] == "eval" else "eval"
        assigned[group] = new_split
        dev_by_cat.update({cat: n if new_split == "dev" else -n for cat, n in Counter(x["category_candidate"] for x in grouped[group]).items()})
    if len(grouped) >= 2 and (dev_size() == 0 or dev_size() == len(items)):
        first = min(grouped, key=lambda g: _stable_order(g, seed))
        assigned[first] = "eval" if dev_size() == len(items) else "dev"
    return assigned


def prepare(root: Path, *, mode: str = "candidate", seed: int = 42, dev_ratio: float = 0.60,
            expect: int = 125) -> dict:
    root = root.resolve()
    catalog_path = root / "source_catalog.csv"
    labels_path = root / "label_review.csv"
    if not catalog_path.is_file():
        raise FileNotFoundError(f"Missing {catalog_path} — run the Commons collector first")
    source = read_csv(catalog_path)
    if not source:
        raise ValueError("Source catalog is empty")
    labels = {r["image_id"]: r for r in read_csv(labels_path)} if labels_path.is_file() else {}
    if len({r.get("image_id") for r in source}) != len(source):
        raise ValueError("Duplicate image_id in source_catalog.csv")
    selected: list[dict] = []
    audits: list[dict] = []
    retained: list[dict] = []
    for row in sorted(source, key=lambda r: r["image_id"]):
        ident = str(row.get("image_id", "")).strip()
        category = str(row.get("category_candidate", "")).strip()
        lab = labels.get(ident, {})
        status = str(lab.get("review_status", "UNREVIEWED")).strip().upper()
        reasons: list[str] = []
        if category not in CATEGORIES:
            reasons.append("invalid_candidate_group")
        if status in {"REJECT", "REPLACE", "DISCARD", "EXCLUDE"}:
            reasons.append("human_rejected")
        if mode == "verified" and not valid_qc_label(lab):
            reasons.append("not_verified_qc_label")
        lic = str(row.get("license", "")).strip()
        if not lic or not any(k in lic.casefold() for k in ALLOWED_LICENSE_HINTS):
            reasons.append("license_missing_or_unrecognized")
        url = str(row.get("source_page", "")).strip()
        if not url.startswith("https://commons.wikimedia.org/"):
            reasons.append("source_not_commons_page")
        img = None
        try:
            img = image_path(root, row.get("image_path", ""))
            if not img.is_file():
                raise FileNotFoundError(img)
            if hash_file(img) != str(row.get("sha256", "")).strip().lower():
                reasons.append("sha256_mismatch")
            with Image.open(img) as im:
                im.verify()
        except (ValueError, OSError, UnidentifiedImageError, FileNotFoundError) as e:
            reasons.append(f"invalid_image:{type(e).__name__}")
        if not reasons:
            for prev in retained:
                if row.get("sha256") == prev.get("sha256") or _near_duplicate(row, prev):
                    reasons.append("duplicate_or_near_duplicate:" + prev["image_id"])
                    break
        scene = str(lab.get("scene_group", "")).strip() or url or ident
        record = {**row, "scene_group": scene, "label_status": status}
        if not reasons:
            selected.append(record)
            retained.append(record)
        audits.append({
            "image_id": ident,
            "candidate_group": category,
            "review_status": status,
            "is_defect": lab.get("is_defect", ""),
            "defect_type": lab.get("defect_type", ""),
            "severity": lab.get("severity", ""),
            "reviewer": lab.get("reviewer", ""),
            "notes": lab.get("notes", ""),
            "source_page": url,
            "quality_flag": row.get("quality_flag", ""),
            "scene_group": scene,
            "reason": ";".join(reasons) if reasons else ("verified" if mode == "verified" else "CANDIDATE_NOT_GROUND_TRUTH"),
        })
    if len(selected) < 2:
        raise ValueError(f"Only {len(selected)} usable images; at least 2 required for dev/eval")
    assignments = split_groups(selected, seed, dev_ratio)
    ready = root / "ready"
    staging = root / ".ready_staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    images: list[dict] = []
    manifest: list[dict] = []
    try:
        for row in selected:
            rel = Path(row["image_path"])
            target = staging / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(image_path(root, str(rel)), target)
            label_row = labels.get(row["image_id"], {})
            light = str(label_row.get("light", "")).strip().lower()
            if light not in {"day", "dusk", "night"}:
                light = "unknown"  # Do NOT infer camera settings or time of day.
            camera = str(label_row.get("camera_id", "")).strip() or "unknown"
            split = assignments[row["scene_group"]]
            images.append({"image_id": row["image_id"], "path": rel.as_posix(),
                           "camera_id": camera, "light": light, "split": split})
            manifest.append({"file_id": row["image_id"], "path": rel.as_posix(),
                             "source": row["source_page"], "license": row["license"],
                             "split": split, "group_id": row["scene_group"], "sha256": hash_file(target)})
        images.sort(key=lambda row: row["image_id"])
        manifest.sort(key=lambda row: row["path"])
        write_csv(staging / "images.csv", images, IMAGE_COLUMNS)
        manifest.append({"file_id": "images_metadata", "path": "images.csv", "source": "T02 real-data adapter",
                         "license": "metadata", "split": "na", "group_id": "metadata",
                         "sha256": hash_file(staging / "images.csv")})
        write_csv(staging / "manifest.csv", manifest, MANIFEST_COLUMNS)
        write_csv(staging / "selection_audit.csv", audits, REVIEW_COLUMNS)
        write_csv(staging / "attribution.csv", [
            {"image_id": r["image_id"], "file_title": r.get("file_title", ""),
             "source_page": r["source_page"], "author": r.get("author", ""),
             "license": r["license"], "license_url": r.get("license_url", ""),
             "sha256": r["sha256"]} for r in selected
        ], ["image_id", "file_title", "source_page", "author", "license", "license_url", "sha256"])
        counts = Counter(row["category_candidate"] for row in selected)
        report = {
            "source": "Wikimedia Commons photos (local-only, attribution in manifest.csv)",
            "mode": mode,
            "labels_verified": mode == "verified",
            "can_claim_official_metrics": False,
            "warning": ("QC labels are provisional and unverified; do not calculate Recall/Precision."
                        if mode == "candidate" else
                        "Human-verified local labels are NOT the instructor hidden GT; evaluate separately."),
            "original_catalog": len(source), "selected": len(selected), "excluded": len(source) - len(selected),
            "target": expect, "target_met": len(selected) >= expect,
            "by_candidate_group": dict(sorted(counts.items())),
            "by_split": dict(sorted(Counter(r["split"] for r in images).items())),
            "seed": seed, "dev_ratio": dev_ratio,
            "camera_metadata": "unknown unless human supplied; never fabricated",
            "light_metadata": "unknown unless human supplied; never inferred from pixels",
            "notes": ["No source photos, labels or pipeline files modified.",
                      "Possible distinct views of the same scene require manual scene_group QA.",
                      "Ready folder is a separate reproducible copy; regenerate before new PoC runs."],
        }
        (staging / "real_dataset_card.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        # Only replace generated ready/ after successful verification and staging.
        for entry in manifest:
            if hash_file(staging / entry["path"]) != entry["sha256"]:
                raise ValueError(f"Staging hash mismatch: {entry['path']}")
        backup = root / ".ready_previous"
        if backup.exists():
            shutil.rmtree(backup)
        if ready.exists():
            ready.rename(backup)
        try:
            staging.rename(ready)
        except Exception:
            if backup.exists() and not ready.exists():
                backup.rename(ready)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        return report
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Convert local Commons traffic photos into T02 input without touching fixtures")
    ap.add_argument("--root", default="data/real/t02_traffic_125", type=Path)
    ap.add_argument("--mode", choices=["candidate", "verified"], default="candidate")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dev-ratio", type=float, default=0.60)
    ap.add_argument("--expect", type=int, default=125)
    args = ap.parse_args(argv)
    if not 0.1 <= args.dev_ratio <= 0.9 or args.expect < 1:
        ap.error("dev-ratio must be between 0.1 and 0.9; expect must be >=1")
    try:
        result = prepare(args.root, mode=args.mode, seed=args.seed, dev_ratio=args.dev_ratio, expect=args.expect)
    except (ValueError, FileNotFoundError, OSError) as error:
        print(f"[T02 real prepare] ERROR: {error}", file=sys.stderr)
        return 2
    print("[T02 real prepare]", json.dumps(result, indent=2, ensure_ascii=False))
    print("Input for pipeline:", (args.root / "ready" / "images.csv").as_posix())
    if not result["target_met"]:
        print(f"[NOTE] Only {result['selected']}/{result['target']} candidate images, preview still usable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
