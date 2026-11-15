
from pathlib import Path
import hashlib
import cv2
import pandas as pd


ROOT = Path("fixtures/t02_raw_qc")
OUTPUT = Path("out/baseline")


def laplacian_variance(image_path):
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"Cannot read image: {image_path}")

    return float(cv2.Laplacian(image, cv2.CV_64F).var())

def verify_manifest():
    manifest = pd.read_csv(ROOT / "manifest.csv")

    passed = 0
    failed = []

    for _, row in manifest.iterrows():
        file_path = ROOT / row["path"]

        if not file_path.is_file():
            failed.append((row["path"], "missing"))
            continue

        data = file_path.read_bytes()
        expected_hash = str(row["sha256"]).strip().lower()
        actual_hash = hashlib.sha256(data).hexdigest()

        # CSV text files may use CRLF on Windows.
        # Binary image files must be checked byte-for-byte.
        if actual_hash != expected_hash and file_path.suffix.lower() == ".csv":
            normalized = data.replace(b"\r\n", b"\n")
            actual_hash = hashlib.sha256(normalized).hexdigest()

        if actual_hash == expected_hash:
            passed += 1
        else:
            failed.append((row["path"], "hash mismatch"))

    print(f"SHA256 hop le: {passed}/{len(manifest)}")

    if failed:
        for path, error in failed:
            print(f"LOI: {path} - {error}")
        raise ValueError("Kiem tra SHA256 that bai")

def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    verify_manifest()
    df = pd.read_csv(ROOT / "images.csv")

    df["laplacian_variance"] = df["path"].apply(
        lambda path: laplacian_variance(ROOT / path)
    )

    # Chỉ sử dụng tập dev để chọn ngưỡng.
    dev = df[df["split"] == "dev"]
    threshold = dev["laplacian_variance"].quantile(0.20)

    # Variance càng thấp thì mức nghi ngờ mờ càng cao.
    df["score"] = threshold - df["laplacian_variance"]

    df["pred_defect_type"] = df["score"].apply(
        lambda score: "blur" if score > 0 else "none"
    )

    ranked = df.sort_values(
        ["score", "image_id"],
        ascending=[False, True]
    )

    ranked.to_csv(
        OUTPUT / "ranked_review.csv",
        columns=["image_id", "score", "pred_defect_type"],
        index=False
    )

    df.to_csv(OUTPUT / "image_statistics.csv", index=False)

    print(f"Tong anh: {len(df)}")
    print(f"Nguong Laplacian: {threshold:.4f}")
    print(f"So anh nghi mo: {(df['pred_defect_type'] == 'blur').sum()}")
    print("\nTop 20 anh uu tien review:")
    print(ranked[["image_id", "score"]].head(20).to_string(index=False))


if __name__ == "__main__":
    main()

def run(ctx):
    """Official Laplacian baseline using the same T02 pipeline as PoC."""
    import json
    import time
    from src.pipeline import run as run_pipeline

    if ctx.track != "t02":
        raise ValueError("Laplacian baseline supports T02 only")

    def score_provider(ctx, data):
        images = data["images"].copy()
        started = time.perf_counter()

        images["laplacian_variance"] = images["path"].apply(
            lambda path: laplacian_variance(ctx.input_dir / path)
        )

        dev_split = ctx.param("dev_split", "dev")
        dev = images[images["split"] == dev_split]

        if dev.empty:
            raise ValueError("Missing dev split for threshold selection")

        threshold = float(
            dev["laplacian_variance"].quantile(0.20)
        )

        images["score"] = threshold - images["laplacian_variance"]
        images["pred_defect_type"] = images["score"].apply(
            lambda value: "blur" if value > 0 else "none"
        )
        images["pred_action"] = images["pred_defect_type"].map({
            "blur": "RECAPTURE",
            "none": "KEEP"
        })
        images["reason"] = "laplacian_variance"

        # Save threshold and reproducibility information.
        threshold_info = {
            "method": "Laplacian Variance",
            "threshold": threshold,
            "selection": "dev 20th percentile",
            "dev_split": dev_split,
            "dev_count": len(dev),
            "total_images": len(images),
            "review_budget": int(ctx.param("budget", 20)),
            "seed": ctx.seed,
        }

        ctx.out("baseline_threshold.json").write_text(
            json.dumps(threshold_info, indent=2),
            encoding="utf-8"
        )

        ctx.stats["baseline_threshold"] = threshold
        ctx.stats["baseline_method"] = "laplacian_variance"
        ctx.stats["scoring_seconds"] = round(
            time.perf_counter() - started, 6
        )

        if ctx.audit:
            ctx.audit.log(
                actor="laplacian_baseline",
                action="threshold_selected",
                item_id="t02_dev",
                after=threshold_info
            )

        return images

    run_pipeline(ctx, score_provider=score_provider)
