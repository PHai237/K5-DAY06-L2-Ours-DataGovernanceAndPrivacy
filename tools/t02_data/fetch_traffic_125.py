#!/usr/bin/env python3
"""Collect up to 125 independently sourced, REAL traffic-photo CANDIDATES.

Source: Wikimedia Commons (search + supplied seed titles). Images remain local
under data/real/ (gitignored), never in the public repository.

Every category is PROVISIONAL, not verified T02 defect ground truth. This tool
cannot guarantee 125 category-correct photos or photographic road relevance.
Stop only after candidate counts are met; human review is still required.

Python 3.11+; Pillow and NumPy (the lab requirements already include these).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import math
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

API = "https://commons.wikimedia.org/w/api.php"
UA = "VinUniT02TrafficResearchCollector/2.0 (https://github.com/PHai237/K5-DAY06-L2-Ours-DataGovernanceAndPrivacy; education; no rehosting)"
GROUPS = ("blur", "glare", "poor_quality", "dark", "normal")
PREFIX = {"blur": "BLUR", "glare": "GLAR", "poor_quality": "POOR", "dark": "DARK", "normal": "NORM"}
# Commons full-text queries are hints, not proof that a file matches the defect.
QUERIES = {
    "blur": [
        '"traffic" "blur"', '"traffic" "motion blur"', '"road" "motion blur"',
        '"traffic" "out of focus"', '"driving" "blurred"', '"windshield" "blurred"',
        '"road" "blurry"', '"cars" "blurred"', '"vehicles" "motion blur"',
        '"car" "rain" "blur"', '"traffic" "bokeh"',
        '"night traffic" "blur"',
    ],
    "glare": [
        '"traffic" "glare"', '"road" "sun glare"', '"windshield" "sun glare"',
        '"driving" "sun glare"', '"highway" "glare"', '"street" "headlight glare"',
        '"streetlight" "glare" "road"', '"intersection" "glare"',
        '"road" "sunlight"', '"traffic" "sun"', '"wet road" "reflections"',
        '"night" "headlight" "road"',
    ],
    "poor_quality": [
        '"traffic" "rain" "windshield"', '"road" "rainy windshield"',
        '"traffic" "low visibility"', '"traffic" "poor visibility"',
        '"road" "fogged windshield"', '"vehicles" "rain blur"',
        '"traffic" "noise" "camera"', '"street" "low resolution"',
        '"road" "fog" "traffic"', '"road" "rain" "windscreen"',
        '"traffic" "CCTV"', '"road" "surveillance camera"',
    ],
    "dark": [
        '"traffic" "at night"', '"night traffic" "road"',
        '"dark road" "traffic"', '"driving" "dark" "road"',
        '"traffic" "low light"', '"street" "night traffic"',
        '"night" "highway" "cars"', '"night" "roads" "vehicles"',
        '"night road" "motorcycle"', '"night" "traffic jam"',
        '"dim" "traffic"', '"road" "underexposed"',
    ],
    "normal": [
        '"daytime" "road traffic"', '"traffic" "daylight"',
        '"traffic" "clear day"', '"cars" "road" "day"',
        '"highway" "cars" "daytime"', '"street traffic" "daytime"',
        '"urban traffic" "sunny"', '"road traffic" "photograph"',
        '"motorway traffic" "day"', '"intersection" "traffic" "day"',
        '"traffic" "Hanoi"', '"road" "vehicles" "daytime"',
    ],
}
TRAFFIC = re.compile(r"\b(traffic|car|cars|road|street|highway|motorway|vehicle|vehicles|driving|drive|truck|lorry|motorcycle|motorbike|bike|bus|buses|taxi|intersection|crossroad|lane|lanes|autobahn|freeway|dashcam|windshield|windscreen|railway crossing|tram|trolleybus|transportation|streetscape|avenue|boulevard|roundabout|highways|roads|motorway|motorways|hanoi|driving|verkehr|straße|strasse|autoroute|autopista|avenida|autosnelweg|ulica)\b", re.I)
NOT_PHOTO = re.compile(r"\b(map|diagram|drawing|illustration|icon|logo|flag|sketch|plan|schematic|vector|emblem|painting|cartoon|render|3d|chart|poster|infographic|satellite|aerial map|rail network|route map|svg)\b", re.I)
IMG_COLS = ["image_id", "category_candidate", "image_path", "file_title", "source_page", "download_url", "original_image_url", "author", "license", "license_url", "sha256", "dhash", "ahash", "width", "height", "source_width", "source_height", "quality_flag", "brightness_median", "dark_fraction", "bright_fraction", "edge_proxy", "review_status", "notes"]
MANIFEST_COLS = ["file_id", "path", "source", "license", "split", "group_id", "sha256"]
LABEL_COLS = ["image_id", "candidate_group", "is_defect", "defect_type", "severity", "reviewer", "notes", "review_status"]


class Network:
    def __init__(self, pause: float):
        self.pause = max(0, pause)
        self.last_call = 0.0
        self.requests = 0

    def fetch(self, url: str, max_bytes: int = 12_000_000, tries: int = 5) -> bytes:
        last = None
        for attempt in range(tries):
            wait = self.pause - (time.monotonic() - self.last_call)
            if wait > 0:
                time.sleep(wait)
            self.last_call = time.monotonic()
            self.requests += 1
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json,image/*;q=0.9,*/*;q=0.6"})
            try:
                with urllib.request.urlopen(req, timeout=35) as resp:
                    length = resp.headers.get("Content-Length")
                    if length and int(length) > max_bytes:
                        raise ValueError("Remote file too large")
                    data = resp.read(max_bytes + 1)
                    if len(data) > max_bytes:
                        raise ValueError("Remote file too large")
                    return data
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code in (400, 401, 403, 404, 410, 415):
                    break
                retry_after = exc.headers.get("Retry-After", "")
                try:
                    delay = float(retry_after)
                except ValueError:
                    delay = min(75, 5 * 2**attempt)
                if exc.code in (429, 503):
                    delay = min(100, max(6, delay))
                    print(f"[RATE LIMIT] HTTP {exc.code}; waiting {delay:g}s (respecting Wikimedia limits)", flush=True)
                else:
                    delay = min(30, 2 * 2**attempt)
                if attempt + 1 < tries:
                    time.sleep(delay)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                last = exc
                if attempt + 1 < tries:
                    time.sleep(min(20, 2 * 2**attempt))
        raise RuntimeError(str(last))

    def api(self, params: dict) -> dict:
        query = urllib.parse.urlencode({"format": "json", "formatversion": "2", **params})
        obj = json.loads(self.fetch(API + "?" + query, max_bytes=4_000_000).decode("utf-8"))
        if obj.get("error"):
            raise RuntimeError(str(obj["error"]))
        return obj


def clean_text(s: object) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", str(s or "")))).strip()


def has_traffic_hint(title: str) -> bool:
    # Presence of a road/vehicle cue in name is required for automated acceptance.
    no_ext = re.sub(r"\.(jpe?g|png)$", "", title, flags=re.I).replace("_", " ")
    return bool(TRAFFIC.search(no_ext)) and not bool(NOT_PHOTO.search(no_ext))


def license_info(ii: dict) -> tuple[str, str, str] | None:
    meta = ii.get("extmetadata") or {}
    v = lambda key: clean_text((meta.get(key) or {}).get("value", ""))
    lic = v("LicenseShortName") or v("License")
    url = v("LicenseUrl")
    author = v("Artist") or v("Attribution") or "UNKNOWN - check source page"
    phrase = (lic + " " + url).lower()
    free = any(x in phrase for x in ("cc0", "cc by", "cc-by", "creativecommons.org/licenses/by/", "public domain", "publicdomain", "pd-"))
    return (lic, url, author) if free else None


def image_check(binary: bytes, min_edge: int) -> tuple[Image.Image, str]:
    with Image.open(io.BytesIO(binary)) as i:
        i.verify()
    with Image.open(io.BytesIO(binary)) as i:
        if i.format not in ("JPEG", "PNG"):
            raise ValueError("Unsupported image type")
        ext = "jpg" if i.format == "JPEG" else "png"
        img = ImageOps.exif_transpose(i).convert("RGB")
    if min(img.size) < min_edge:
        raise ValueError(f"Image too small: {img.size}")
    # No transcoding: provenance hash refers to the exact saved downloaded bytes.
    return img, ext


def d_hash(img: Image.Image) -> str:
    small = np.asarray(img.convert("L").resize((9, 8), Image.Resampling.LANCZOS), dtype=np.int16)
    bits = small[:, 1:] > small[:, :-1]
    n = 0
    for b in bits.flat:
        n = (n << 1) | bool(b)
    return f"{n:016x}"


def a_hash(img: Image.Image) -> str:
    small = np.asarray(img.convert("L").resize((8, 8), Image.Resampling.LANCZOS), dtype=np.float32)
    bits = small > np.median(small)
    n = 0
    for b in bits.flat:
        n = (n << 1) | bool(b)
    return f"{n:016x}"


def bits_diff(x: str, y: str) -> int:
    try:
        return (int(x, 16) ^ int(y, 16)).bit_count()
    except (ValueError, TypeError):
        return 64


def looks_duplicate(new: dict, existing: list[dict]) -> bool:
    for old in existing:
        if new["sha256"] == old.get("sha256"):
            return True
        # Two independent hashes and similar aspect ratio reduce false-positive dedupe.
        try:
            ratio_a = int(new["width"]) / int(new["height"])
            ratio_b = int(old["width"]) / int(old["height"])
            same_ratio = abs(math.log(ratio_a / ratio_b)) < 0.055
        except (TypeError, ValueError, ZeroDivisionError):
            same_ratio = False
        if same_ratio and bits_diff(new["dhash"], old.get("dhash", "")) <= 5 and bits_diff(new["ahash"], old.get("ahash", "")) <= 7:
            return True
    return False


def cues(img: Image.Image) -> dict:
    # Coarse thumbnail cues; never use them as GT or teacher-eval numbers.
    img = img.copy()
    img.thumbnail((512, 512))
    g = np.asarray(img.convert("L"), dtype=np.float32)
    med = float(np.median(g))
    dark = float(np.mean(g < 50))
    bright = float(np.mean(g >= 245))
    edge = float(np.mean(np.abs(np.diff(g, axis=1)))) if g.shape[1] > 1 else 0.0
    return {"brightness_median": round(med, 2), "dark_fraction": round(dark, 4), "bright_fraction": round(bright, 4), "edge_proxy": round(edge, 2)}


def quality_hint(group: str, metrics: dict) -> str:
    med, dark, bright, edges = (metrics[x] for x in ("brightness_median", "dark_fraction", "bright_fraction", "edge_proxy"))
    if group == "dark":
        return "LIKELY_CUE" if med < 87 or dark > 0.35 else "UNCERTAIN_NIGHT_NOT_QC_DEFECT"
    if group == "normal":
        return "UNCERTAIN_POSSIBLY_BAD" if med < 55 or med > 228 or edges < 4 else "LIKELY_CUE"
    if group == "blur":
        return "LIKELY_CUE" if edges < 10 else "UNCERTAIN_MOTION_OR_ARTISTIC_BLUR"
    if group == "glare":
        return "LIKELY_CUE" if bright > .017 else "UNCERTAIN_LIGHT_NOT_NECESSARILY_GLARE"
    return "UNCERTAIN_POOR_QUALITY_NOT_T02_COMPRESSION"


def csv_read(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def csv_write(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(temp, path)


def json_write(path: Path, obj: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def sheet_html(rows: list[dict], target: int) -> str:
    sections = []
    for group in GROUPS:
        cards = []
        for ent in rows:
            if ent.get("category_candidate") != group:
                continue
            img = html.escape(ent["image_path"], quote=True)
            page = html.escape(ent["source_page"], quote=True)
            cap = html.escape(ent["file_title"][:85])
            cue = html.escape(ent.get("quality_flag", ""))
            cards.append(f'<figure><img loading="lazy" src="{img}"><figcaption><b>{html.escape(ent["image_id"])}</b> · <small>{cue}</small><p>{cap}</p><a href="{page}" target="_blank" rel="noopener noreferrer">Source + license</a></figcaption></figure>')
        sections.append(f'<h2>{group} ({len(cards)}/{target})</h2><div class="grid">{"".join(cards)}</div>')
    return '''<!doctype html><html lang="vi"><head><meta charset="utf-8"><title>T02 125 Traffic · visual QA</title><style>
body{font:14px system-ui,sans-serif;background:#f2f5f9;color:#18212d;max-width:1350px;margin:auto;padding:18px}
.warn{padding:14px;background:#fff4d6;border-radius:9px;line-height:1.5}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(205px,1fr));gap:13px}
figure{background:white;margin:0;padding:9px;border-radius:10px;box-shadow:0 1px 6px #0002}
img{width:100%;height:165px;object-fit:contain;background:#e1e5ec}figcaption{line-height:1.35;overflow-wrap:anywhere}
a{color:#1764b1}p{margin:8px 0}</style></head><body><h1>T02 · Ảnh giao thông thật — danh sách cần xác minh</h1><div class="warn">
<b>Chưa phải nhãn thật!</b> Mọi ảnh mới chỉ được tuyển chọn theo tiêu đề, nguồn và chỉ số thị giác đơn giản. Mờ nghệ thuật, đêm rõ, nắng không lóa và ảnh mưa vẫn có thể đạt QC.
Xem ảnh và xác nhận có đường/phương tiện, đúng nhãn và giấy phép trước khi dùng làm dataset. Không push ảnh có người/biển số thật lên GitHub public.
</div>''' + "".join(sections) + "</body></html>"


def persist(out: Path, rows: list[dict], target: int, errors: list[str], requests: int) -> None:
    manifest = [{"file_id": r["image_id"], "path": r["image_path"], "source": r["source_page"], "license": r["license"], "split": "unassigned", "group_id": r["file_title"], "sha256": r["sha256"]} for r in rows]
    images = [{"image_id": r["image_id"], "path": r["image_path"], "camera_id": "unknown", "light": "unknown", "split": "unassigned"} for r in rows]
    previous_labels = {r.get("image_id"): r for r in csv_read(out / "label_review.csv")}
    labels = [previous_labels.get(r["image_id"], {"image_id": r["image_id"], "candidate_group": r["category_candidate"], "is_defect": "", "defect_type": "", "severity": "", "reviewer": "", "notes": "", "review_status": "UNREVIEWED"}) for r in rows]
    csv_write(out / "source_catalog.csv", rows, IMG_COLS)
    csv_write(out / "manifest.csv", manifest, MANIFEST_COLS)
    csv_write(out / "images.csv", images, ["image_id", "path", "camera_id", "light", "split"])
    csv_write(out / "label_review.csv", labels, LABEL_COLS)
    (out / "contact_sheet.html").write_text(sheet_html(rows, target), encoding="utf-8")
    counts = dict(Counter(r["category_candidate"] for r in rows))
    json_write(out / "collection_log.json", {
        "requested": target * len(GROUPS), "collected": len(rows), "counts": {g: counts.get(g, 0) for g in GROUPS},
        "target_per_group": target, "complete_candidate_counts": all(counts.get(g, 0) == target for g in GROUPS),
        "status": "CANDIDATE_COLLECTION_ONLY_NOT_VERIFIED_LABELS", "requires_human_validation": True,
        "api_requests_this_run": requests, "skipped_examples": errors[-100:],
    })


def seed_titles(csv_path: Path, group: str) -> list[str]:
    rows = [r for r in csv_read(csv_path) if r.get("category", "").strip() == group]
    rows.sort(key=lambda r: int(r.get("priority", "9999") or "9999"))
    return [r["commons_file_title"].strip().removeprefix("File:") for r in rows if r.get("commons_file_title", "").strip()]


def search_titles(net: Network, phrase: str, limit: int = 40) -> list[str]:
    obj = net.api({"action": "query", "list": "search", "srsearch": phrase, "srnamespace": 6, "srlimit": min(limit, 50)})
    return [r["title"].removeprefix("File:") for r in obj.get("query", {}).get("search", []) if r.get("title", "").startswith("File:")]


def metadata_batch(net: Network, names: list[str], width: int) -> dict[str, dict]:
    # imageinfo metadata is expensive; query small batches, not 100s in one API call.
    if not names:
        return {}
    obj = net.api({"action": "query", "prop": "imageinfo", "titles": "|".join("File:" + n for n in names),
                   "iiprop": "url|size|mime|extmetadata", "iiurlwidth": width})
    out = {}
    for page in obj.get("query", {}).get("pages", []):
        infos = page.get("imageinfo", [])
        if infos:
            out[page.get("title", "").removeprefix("File:").casefold()] = infos[0]
    return out


def candidate_iter(net: Network, group: str, seed_file: Path, seed: int, max_search: int, skip_seeds: bool = False):
    seen = set()
    # First use known Commons file pages from the previously proven 50-image tool.
    if not skip_seeds:
        for title in seed_titles(seed_file, group):
            key = title.casefold()
            if key not in seen and has_traffic_hint(title):
                seen.add(key)
                yield title
    randomizer = random.Random(seed + GROUPS.index(group))
    queries = list(QUERIES[group])
    randomizer.shuffle(queries)
    n = 0
    for query in queries:
        if n >= max_search:
            break
        try:
            found = search_titles(net, query)
        except RuntimeError as e:
            print(f"[SEARCH WARN] {group}: {query} : {e}", flush=True)
            continue
        for title in found:
            key = title.casefold()
            if key in seen or not has_traffic_hint(title):
                continue
            if not re.search(r"\.(jpe?g|png)$", title, re.I):
                continue
            seen.add(key)
            n += 1
            yield title
            if n >= max_search:
                break


def restore(out: Path) -> list[dict]:
    rows = csv_read(out / "source_catalog.csv")
    for row in rows:
        path = out / row["image_path"]
        if not path.is_file():
            raise RuntimeError(f"Existing catalog points to missing file: {path}; fix before resuming")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if sha != row["sha256"]:
            raise RuntimeError(f"Existing file hash mismatch: {path}; do not silently overwrite")
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Wikimedia Commons T02: 25 candidates × 5 groups (125), resumable and deduplicated")
    ap.add_argument("--candidates", type=Path, default=Path(__file__).with_name("candidate_sources.csv"))
    ap.add_argument("--out", type=Path, default=Path("data/real/t02_traffic_125"))
    ap.add_argument("--per-group", type=int, default=25)
    ap.add_argument("--max-width", type=int, default=960)
    ap.add_argument("--min-edge", type=int, default=320)
    ap.add_argument("--pause", type=float, default=1.2, help="Minimum time between requests (seconds)")
    ap.add_argument("--max-search", type=int, default=360, help="Search candidates considered per group")
    ap.add_argument("--max-downloads", type=int, default=100, help="Max image download attempts per group")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--skip-seeds", action="store_true", help="Search NEW photos without retrying the 68 old candidate file titles")
    a = ap.parse_args(argv)
    if a.per_group < 1 or a.per_group > 500 or a.max_width < 480 or a.min_edge < 150:
        ap.error("Invalid --per-group / --max-width / --min-edge")
    a.out.mkdir(parents=True, exist_ok=True)
    try:
        rows = restore(a.out)
    except RuntimeError as e:
        print("[ERROR]", e, file=sys.stderr)
        return 3
    net = Network(a.pause)
    errors = []
    known = {r.get("file_title", "").casefold() for r in rows}
    for group in GROUPS:
        current = sum(r.get("category_candidate") == group for r in rows)
        print(f"\n[GROUP] {group}: {current}/{a.per_group} existing", flush=True)
        if current >= a.per_group:
            continue
        attempts = 0
        pending = []
        exhausted = False
        itr = candidate_iter(net, group, a.candidates, a.seed, a.max_search, a.skip_seeds)
        while current < a.per_group and attempts < a.max_downloads and not exhausted:
            while len(pending) < min(10, a.per_group - current):
                try:
                    title = next(itr)
                except StopIteration:
                    exhausted = True
                    break
                if title.casefold() not in known:
                    pending.append(title)
            if not pending:
                break
            candidates, pending = pending, []
            try:
                infos = metadata_batch(net, candidates, a.max_width)
            except Exception as e:
                msg = f"{group}: metadata batch: {e}"
                print("[WARN]", msg[:160], flush=True)
                errors.append(msg)
                continue
            for title in candidates:
                if current >= a.per_group or attempts >= a.max_downloads:
                    break
                known.add(title.casefold())
                ii = infos.get(title.casefold())
                if not ii:
                    continue
                if ii.get("mime") not in ("image/jpeg", "image/png"):
                    continue
                lic = license_info(ii)
                if lic is None:
                    continue
                image_url = ii.get("thumburl") or ii.get("url")
                if not image_url:
                    continue
                attempts += 1
                try:
                    binary = net.fetch(image_url)
                    img, ext = image_check(binary, a.min_edge)
                    dims = img.size
                    check = {"sha256": hashlib.sha256(binary).hexdigest(), "dhash": d_hash(img),
                             "ahash": a_hash(img), "width": dims[0], "height": dims[1]}
                    if looks_duplicate(check, rows):
                        print("[DUPE]", title[:80], flush=True)
                        continue
                    measure = cues(img)
                    current += 1
                    ident = PREFIX[group] + "_" + f"{current:03d}"
                    path = f"images/{group}/{ident}.{ext}"
                    dest = a.out / path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    tmp = dest.with_suffix(dest.suffix + ".tmp")
                    tmp.write_bytes(binary)
                    os.replace(tmp, dest)
                    author_license, license_url, author = lic
                    page = "https://commons.wikimedia.org/wiki/" + urllib.parse.quote("File:" + title.replace(" ", "_"), safe=":()")
                    ent = {"image_id": ident, "category_candidate": group, "image_path": path, "file_title": title,
                           "source_page": page, "download_url": image_url, "original_image_url": ii.get("url", ""),
                           "author": author, "license": author_license, "license_url": license_url, **check,
                           "source_width": ii.get("width", ""), "source_height": ii.get("height", ""),
                           "quality_flag": quality_hint(group, measure), **measure,
                           "review_status": "UNREVIEWED", "notes": "Autoselected Commons photo; check traffic + T02 defect manually"}
                    rows.append(ent)
                    persist(a.out, rows, a.per_group, errors, net.requests)
                    print(f"[OK] {ident} ({current}/{a.per_group}) {title[:70]} — {ent['quality_flag']}", flush=True)
                except (RuntimeError, ValueError, OSError, UnidentifiedImageError) as e:
                    msg = f"{group} | {title} | {type(e).__name__}: {e}"
                    errors.append(msg)
                    print("[SKIP]", msg[:150], flush=True)
        if current < a.per_group:
            print(f"[INCOMPLETE] {group}: {current}/{a.per_group}. Re-run later; no invented images.", flush=True)
        else:
            print(f"[COMPLETE candidates] {group}: {current}/{a.per_group}", flush=True)
        persist(a.out, rows, a.per_group, errors, net.requests)
    counts = Counter(r["category_candidate"] for r in rows)
    print("\nFINAL CANDIDATES:", ", ".join(f"{g}={counts[g]}/{a.per_group}" for g in GROUPS))
    print("Output:", a.out.resolve())
    print("Open contact_sheet.html; labels are NOT confirmed ground truth.")
    if any(counts[g] < a.per_group for g in GROUPS):
        print("Partial collection due to image scarcity/HTTP limits. Re-run same command to resume.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
