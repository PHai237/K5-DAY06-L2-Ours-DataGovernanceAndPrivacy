
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
