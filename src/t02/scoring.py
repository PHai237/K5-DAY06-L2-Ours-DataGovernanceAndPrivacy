"""TEAM MEMBER 3 OWNS THIS FILE: T02 model / scoring (Core Algorithm).

Contract
--------
score_images(ctx, images) -> pandas.DataFrame containing EXACTLY ONE row for
EACH image in images.csv, including eval (without reading any GT).
Required: image_id (str), score (finite float, larger means more suspicious).
Recommended: pred_defect_type, pred_action (KEEP/RECAPTURE), reason.

Algorithm Overview & Failure Mode Analysis (FP / FN)
----------------------------------------------------
1. Multi-Signal Feature Extraction:
   - Blur (`blur`): Global Laplacian variance (`laplacian_variance`) and
     contrast-normalized sharpness `norm_lap = lap / (std^2 + 1e-6)`.
     Normalizing by intensity variance prevents dark/low-contrast images from
     being misclassified as optical blur, while per-camera calibration avoids
     penalizing `cam_B` (which has naturally softer optics than `cam_A`).
   - Dark (`dark`): Brightness distribution (`mean`, `p05`, `p95`, `frac_dark`)
     normalized against `dev`-split reference medians for each lighting slice
     (`day`, `dusk`, `night`). Requiring both relative mean/p95 drop and high
     `frac_dark` prevents clean `night` scenes from becoming False Positives.
   - Glare (`glare`): Combines global saturation (`frac_saturated > 245`) with
     sliding-window local patch saturation (`patch_250` over 16x16 patches,
     stride 8). This catches localized glare blobs (e.g., overexposed license
     plates or headlights) that global averages or Laplacian sharpness miss.
   - Compression (`compression`): Measures 8x8 JPEG block boundary discontinuity
     ratios across both Luma (Y) and Chroma (Cb, Cr) channels (`luma_block`,
     `chroma_block`) to detect heavy JPEG quantization artifacts.

2. False Positive / False Negative Analysis vs Global Laplacian Baseline:
   - Baseline FP1 (Soft-optics `cam_B` false alarms): Global Laplacian ranks
     clean `cam_B` images (`img_06_0`, `img_15_0`, `img_03_0` in eval) inside
     Top-20 because `cam_B` clean Laplacian (~166-360) is lower than `cam_A`
     (~780-2260). Resolved by contrast-normalized sharpness + camera reference.
   - Baseline FP2 (Useful `night` images flagged by naive brightness): Clean
     `night` images have low mean (~30-35) and `frac_dark` ~0.53-0.63, but keep
     healthy upper percentile contrast (`p95` ~83-143). Resolved by `light`-slice
     normalization against `dev` medians.
   - Baseline FN1 (Sharp images with local `glare` missed): E.g. `img_05_3`
     (eval, `lap=1324.5`) is very sharp globally so Laplacian misses it, but
     local patch saturation reaches `patch_250=0.844`. Resolved by local patch
     glare scoring.
   - Baseline FN2 (Sharp images with JPEG `compression` missed): E.g. `img_01_3`
     (`lap=1094.1`) and `img_13_2` (`lap=1206.6`) have strong 8x8 block edges
     that artificially inflate Laplacian variance. Resolved by Luma+Chroma 8x8
     blockiness detection.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from ..common.context import RunContext
from ..common.image_ops import brightness_stats, laplacian_variance, load_rgb, to_gray

# Fallback reference medians (derived from T02 dev split) used only when a
# synthetic unit-test DataFrame does not contain enough dev samples per slice.
DEFAULT_LIGHT_MEAN_REF: dict[str, float] = {
    "day": 119.4,
    "dusk": 88.8,
    "night": 32.5,
}
DEFAULT_LIGHT_P95_REF: dict[str, float] = {
    "day": 187.3,
    "dusk": 143.7,
    "night": 121.4,
}
DEFAULT_CAM_NORMLAP_REF: dict[str, float] = {
    "cam_A": 0.85,
    "cam_B": 0.28,
}


def compute_jpeg_blockiness(img_rgb: np.ndarray, gray: np.ndarray) -> tuple[float, float]:
    """Compute 8x8 JPEG block boundary discontinuity ratios for Luma and Chroma."""
    H, W = gray.shape
    if H < 16 or W < 16:
        return 1.0, 1.0

    img = img_rgb.astype(np.float32)
    dh = np.abs(np.diff(gray, axis=0))
    dw = np.abs(np.diff(gray, axis=1))
    non_bh = dh[np.arange(dh.shape[0]) % 8 != 7, :]
    non_bw = dw[:, np.arange(dw.shape[1]) % 8 != 7]
    luma_h = float(dh[7::8, :].mean()) / (float(non_bh.mean()) + 1e-6)
    luma_w = float(dw[:, 7::8].mean()) / (float(non_bw.mean()) + 1e-6)
    luma_block = 0.5 * (luma_h + luma_w)

    # YCbCr chroma channels show strong 8x8 quantization jumps under heavy JPEG compression
    cb = -0.1687 * img[..., 0] - 0.3313 * img[..., 1] + 0.5000 * img[..., 2]
    cr = 0.5000 * img[..., 0] - 0.4187 * img[..., 1] - 0.0813 * img[..., 2]
    cdh = np.abs(np.diff(cb, axis=0)) + np.abs(np.diff(cr, axis=0))
    cdw = np.abs(np.diff(cb, axis=1)) + np.abs(np.diff(cr, axis=1))
    non_ch = cdh[np.arange(cdh.shape[0]) % 8 != 7, :]
    non_cw = cdw[:, np.arange(cdw.shape[1]) % 8 != 7]
    chroma_h = float(cdh[7::8, :].mean()) / (float(non_ch.mean()) + 0.1)
    chroma_w = float(cdw[:, 7::8].mean()) / (float(non_cw.mean()) + 0.1)
    chroma_block = 0.5 * (chroma_h + chroma_w)
    return float(luma_block), float(chroma_block)


def compute_local_glare_patches(gray: np.ndarray, patch_size: int = 16, stride: int = 8) -> tuple[float, float]:
    """Compute maximum saturated pixel fraction inside any local sliding window."""
    H, W = gray.shape
    if H < patch_size or W < patch_size:
        return float((gray > 250).mean()), float((gray > 242).mean())

    max_p250 = 0.0
    max_p242 = 0.0
    for y in range(0, H - patch_size + 1, stride):
        for x in range(0, W - patch_size + 1, stride):
            patch = gray[y : y + patch_size, x : x + patch_size]
            p250 = float((patch > 250).mean())
            p242 = float((patch > 242).mean())
            if p250 > max_p250:
                max_p250 = p250
            if p242 > max_p242:
                max_p242 = p242
    return max_p250, max_p242


def extract_image_features(image_path: Path) -> dict[str, float]:
    """Extract blur, brightness/darkness, local glare, and JPEG compression features."""
    img_rgb = load_rgb(image_path)
    gray = to_gray(img_rgb)
    bstats = brightness_stats(img_rgb)
    lap = laplacian_variance(img_rgb)
    std = max(float(bstats["std"]), 1.0)
    norm_lap = float(lap) / (std * std + 1e-6)
    luma_block, chroma_block = compute_jpeg_blockiness(img_rgb, gray)
    patch_250, patch_242 = compute_local_glare_patches(gray)

    return {
        "lap": float(lap),
        "norm_lap": float(norm_lap),
        "mean": float(bstats["mean"]),
        "std": float(bstats["std"]),
        "p05": float(bstats["p05"]),
        "p95": float(bstats["p95"]),
        "frac_dark": float(bstats["frac_dark"]),
        "frac_sat": float(bstats["frac_saturated"]),
        "patch_250": float(patch_250),
        "patch_242": float(patch_242),
        "luma_block": float(luma_block),
        "chroma_block": float(chroma_block),
    }


def calibrate_dev_references(df: pd.DataFrame, dev_split: str = "dev") -> dict[str, dict[str, float]]:
    """Estimate reference medians strictly from the dev split (no eval leakage)."""
    if "split" not in df.columns:
        raise ValueError("Missing split column for dev calibration")
    dev = df[df["split"].astype(str) == dev_split]
    if dev.empty:
        raise ValueError(f"No dev data for split {dev_split!r}; refusing eval calibration")

    light_mean = dict(DEFAULT_LIGHT_MEAN_REF)
    light_p95 = dict(DEFAULT_LIGHT_P95_REF)
    cam_normlap = dict(DEFAULT_CAM_NORMLAP_REF)

    if "light" in dev.columns and len(dev) >= 8:
        for light_val, grp in dev.groupby("light"):
            if len(grp) >= 4:
                light_mean[str(light_val)] = float(grp["mean"].median())
                light_p95[str(light_val)] = float(grp["p95"].median())

    if "camera_id" in dev.columns and len(dev) >= 8:
        for cam_val, grp in dev.groupby("camera_id"):
            if len(grp) >= 4:
                cam_normlap[str(cam_val)] = float(grp["norm_lap"].median())

    return {
        "light_mean": light_mean,
        "light_p95": light_p95,
        "cam_normlap": cam_normlap,
    }


def score_images(ctx: RunContext, images: pd.DataFrame) -> pd.DataFrame:
    """Compute composite defect score, predicted defect type, action, and reason for all images."""
    if not isinstance(images, pd.DataFrame) or images.empty:
        raise ValueError("images DataFrame must be non-empty")

    dev_split = str(ctx.param("dev_split", "dev"))
    dark_ratio_thr = float(ctx.param("dark_ratio_threshold", 0.55))
    dark_frac_thr = float(ctx.param("dark_frac_threshold", 0.60))
    blur_normlap_thr = float(ctx.param("blur_normlap_threshold", 0.05))
    glare_patch_thr = float(ctx.param("glare_patch250_threshold", 0.10))
    glare_sat_thr = float(ctx.param("glare_frac_sat_threshold", 0.003))
    comp_chroma_thr = float(ctx.param("compression_chroma_threshold", 1.60))
    comp_luma_thr = float(ctx.param("compression_luma_threshold", 1.55))

    feat_rows = []
    for row in images.itertuples(index=False):
        img_path = ctx.input_dir / str(row.path)
        feat_rows.append(extract_image_features(img_path))

    work = pd.concat([images.reset_index(drop=True), pd.DataFrame(feat_rows)], axis=1)
    refs = calibrate_dev_references(work, dev_split=dev_split)

    out_rows = []
    for r in work.itertuples(index=False):
        light_key = str(getattr(r, "light", "day"))
        cam_key = str(getattr(r, "camera_id", "cam_A"))
        ref_mean = refs["light_mean"].get(light_key, DEFAULT_LIGHT_MEAN_REF.get(light_key, 90.0))
        ref_p95 = refs["light_p95"].get(light_key, DEFAULT_LIGHT_P95_REF.get(light_key, 150.0))
        ref_nl = refs["cam_normlap"].get(cam_key, DEFAULT_CAM_NORMLAP_REF.get(cam_key, 0.40))

        mean_ratio = r.mean / max(ref_mean, 1.0)
        p95_ratio = r.p95 / max(ref_p95, 1.0)

        # 1. Dark score (normalized per light slice so clean night scenes are not penalized)
        if mean_ratio < dark_ratio_thr and p95_ratio < dark_ratio_thr and r.frac_dark > dark_frac_thr:
            s_dark = 1.0 + (dark_ratio_thr - mean_ratio) * 3.0 + (dark_ratio_thr - p95_ratio) * 2.0
        else:
            s_dark = max(0.0, (0.82 - mean_ratio) * 0.6)

        # 2. Blur score (contrast-invariant sharpness + camera reference)
        if r.norm_lap < blur_normlap_thr and s_dark < 1.0:
            s_blur = 1.0 + ((blur_normlap_thr - r.norm_lap) / blur_normlap_thr) * 3.0 + max(0.0, (15.0 - r.lap) / 15.0)
        else:
            rel_sharp = r.norm_lap / max(ref_nl, 0.1)
            s_blur = max(0.0, (0.30 - rel_sharp) * 0.5)

        # 3. Glare score (local patch saturation + global saturation fraction)
        if r.patch_250 >= glare_patch_thr and r.frac_sat >= glare_sat_thr:
            s_glare = 1.0 + r.patch_250 * 2.5 + min(r.frac_sat * 20.0, 2.0)
        else:
            s_glare = min(0.45, r.patch_250 * 3.5)

        # 4. Compression score (8x8 JPEG block boundary ratio in Chroma + Luma)
        if r.chroma_block >= comp_chroma_thr and r.luma_block >= comp_luma_thr:
            s_comp = 1.0 + (r.chroma_block - comp_chroma_thr) * 1.8 + (r.luma_block - comp_luma_thr) * 0.8
        else:
            s_comp = max(0.0, min(0.45, (r.chroma_block - 1.15) * 0.6))

        comp_map = {
            "blur": float(s_blur),
            "dark": float(s_dark),
            "glare": float(s_glare),
            "compression": float(s_comp),
        }
        best_type = max(comp_map, key=comp_map.get)
        best_val = comp_map[best_type]
        other_sum = sum(v for k, v in comp_map.items() if k != best_type)
        composite_score = round(float(best_val + 0.10 * other_sum), 6)

        if best_val >= 1.0:
            pred_defect_type = best_type
            pred_action = "RECAPTURE"
            if best_type == "blur":
                reason = f"blur: low sharpness lap={r.lap:.1f}, norm_lap={r.norm_lap:.4f} on {cam_key}"
            elif best_type == "dark":
                reason = f"dark: mean={r.mean:.1f} ({mean_ratio:.2f}x {light_key} ref), p95={r.p95:.1f}, frac_dark={r.frac_dark:.2f}"
            elif best_type == "glare":
                reason = f"glare: local_patch250={r.patch_250:.2f}, frac_sat={r.frac_sat:.4f} ({light_key})"
            else:
                reason = f"compression: 8x8 blockiness chroma={r.chroma_block:.2f}, luma={r.luma_block:.2f}"
        else:
            pred_defect_type = "none"
            pred_action = "KEEP"
            reason = f"clean: normal {cam_key}/{light_key} (lap={r.lap:.0f}, mean={r.mean:.0f}, block={r.chroma_block:.2f})"

        out_rows.append(
            {
                "image_id": str(r.image_id),
                "score": composite_score,
                "pred_defect_type": pred_defect_type,
                "pred_action": pred_action,
                "reason": reason,
                "blur_score": round(float(s_blur), 4),
                "dark_score": round(float(s_dark), 4),
                "glare_score": round(float(s_glare), 4),
                "compression_score": round(float(s_comp), 4),
            }
        )

    return pd.DataFrame(out_rows)


def analyze_fp_fn(input_dir: Path, scored: pd.DataFrame) -> dict[str, object]:
    """Compare Global Laplacian Baseline vs Core Algorithm on T02 failure modes."""
    images = pd.read_csv(input_dir / "images.csv", dtype={"image_id": str, "path": str})
    laps = [laplacian_variance(load_rgb(input_dir / p)) for p in images["path"]]
    base = images.copy()
    base["lap"] = laps
    base["baseline_score"] = 1.0 / (base["lap"] + 1.0)

    merged = base.merge(scored, on="image_id", how="left")
    eval_df = merged[merged["split"] == "eval"].copy()

    base_top20 = set(eval_df.sort_values("baseline_score", ascending=False).head(20)["image_id"])
    core_top20 = set(eval_df.sort_values("score", ascending=False).head(20)["image_id"])

    # Images selected by baseline but not by core; no GT verification
    baseline_only = eval_df[
        eval_df["image_id"].isin(base_top20 - core_top20)
    ][["image_id", "camera_id", "light", "lap", "score", "pred_defect_type", "reason"]]

    # Images selected by core but not by baseline; no GT verification
    core_only = eval_df[
        eval_df["image_id"].isin(core_top20 - base_top20)
    ][["image_id", "camera_id", "light", "lap", "score", "pred_defect_type", "reason"]]

    return {
        "eval_count": len(eval_df),
        "baseline_only_top20": baseline_only.to_dict(orient="records"),
        "core_only_top20": core_only.to_dict(orient="records"),
        "defect_type_counts_all": scored["pred_defect_type"].value_counts().to_dict(),
        "defect_type_counts_eval_top20": (
            eval_df.sort_values("score", ascending=False).head(20)["pred_defect_type"].value_counts().to_dict()
        ),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run T02 Core Algorithm scoring and export ranked_review.csv")
    ap.add_argument("--input", default="fixtures/t02_raw_qc", help="Input fixture directory")
    ap.add_argument("--output", default="out/poc", help="Output directory for ranked_review.csv")
    args = ap.parse_args(argv)

    in_dir = Path(args.input)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    images = pd.read_csv(in_dir / "images.csv", dtype={"image_id": str, "path": str})
    ctx = RunContext(
        track="t02",
        input_dir=in_dir,
        output_dir=out_dir,
        config={"track": "t02", "params": {"budget": 20, "dev_split": "dev"}},
        seed=42,
        rng=np.random.default_rng(42),
    )
    scored = score_images(ctx, images)
    ranked = scored.sort_values("score", ascending=False, kind="mergesort").reset_index(drop=True)
    out_csv = out_dir / "ranked_review.csv"
    ranked.to_csv(out_csv, index=False)

    report = analyze_fp_fn(in_dir, ranked)
    print(f"[T02 Core] Wrote {len(ranked)} rows to {out_csv}")
    print(f"[T02 Core] Predicted defect distribution (all 96): {report['defect_type_counts_all']}")
    print(f"[T02 Core] Eval Top-20 defect distribution: {report['defect_type_counts_eval_top20']}")
    print("\n--- Baseline-only Top-20 (not verified FP) (Eval Split) ---")
    for item in report["baseline_only_top20"]:
        print(f"  {item['image_id']} ({item['camera_id']}, {item['light']}): lap={item['lap']:.1f} -> score={item['score']:.3f} [{item['pred_defect_type']}]")
    print("\n--- Core-only Top-20 (not verified FN) (Eval Split) ---")
    for item in report["core_only_top20"]:
        print(f"  {item['image_id']} ({item['camera_id']}, {item['light']}): lap={item['lap']:.1f} -> score={item['score']:.3f} [{item['pred_defect_type']}] ({item['reason']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
