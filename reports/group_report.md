# Group Report — Day 06 Data Lab (Field-to-Release PoC)

> Báo cáo nhóm G02, giữ cấu trúc mục **00–11** và **Bảng 1–3** của mẫu VinUni. Các số chưa có ground truth (GT) hoặc bằng chứng chạy evaluator được ghi **N/A**, không thay bằng ước lượng.

## 00 · Header

| Mục | Giá trị |
|---|---|
| Group ID | **G02** (theo `configs/lab.yaml`) |
| Challenge | **T02 · Raw QC Triage** — blur / glare / dark / compression |
| Thành viên (4) + vai trò | **1. Phạm Hải** — Lead/Integrator, review & report; **2. Phạm Việt Hoàng** — Data & Baseline; **3. Bùi Quốc Bình** — Core Algorithm; **4. Thảo Linh** — QA / Metric & Testing (chưa xác minh họ tên đầy đủ) |
| Git URL | https://github.com/PHai237/K5-DAY06-L2-Ours-DataGovernanceAndPrivacy |
| Commit `main` tại lượt kiểm tra | `2460a8b` (đã push thành công) |
| Tag `demo-180m` | Chưa xác minh có tag; **không khẳng định đã tạo** |
| Tag `final-24h` | Chưa xác minh có tag; **không khẳng định đã tạo** |
| Deadline (giờ VN) | 15/11/2026, **14:00** (theo thông tin nhóm trưởng cung cấp) |

## 01 · Problem statement

- **Đối tượng / hậu quả:** đội thu thập và gán nhãn ảnh giao thông; nếu lỗi ảnh thô không được phát hiện, dữ liệu không đạt chất lượng đi tiếp vào pipeline. Nếu báo lỗi nhầm, lãng phí thời gian review hoặc yêu cầu chụp lại.
- **Điểm nghẽn:** không thể kiểm tra thủ công tất cả ảnh; ngân sách cố định **B=20** ảnh được ưu tiên cho người review.
- **Đầu vào → đầu ra:** ảnh, `images.csv`, `manifest.csv` → kiểm hash → trích xuất feature → `ranked_review.csv` → `review_queue.csv` / `contact_sheet.html` → `review_results.csv`, `audit_log.jsonl`, `decision.json`.
- **GO / HOLD / REWORK:** quyết định dựa trên bằng chứng human review, quy tắc `src/t02/review_flow.py`; khi chưa đóng đủ Top-20 thì **HOLD / REVIEW_INCOMPLETE** (đã quan sát). Không tự gắn nhãn `GO` khi chưa review.
- **Giả định cần domain owner / DPO / legal xác nhận:** tiêu chí chất lượng ảnh, quyền dùng ảnh Wikimedia Commons theo từng file, bảo vệ PII (mặt, biển số), quyền công bố dữ liệu.

## 02 · Data & provenance

| Split | N | Nguồn / link | License | Synthetic? |
|---|---:|---|---|---|
| dev (fixture) | 56 | `fixtures/t02_raw_qc/` | Theo `manifest.csv` của fixture, cần đối chiếu khi nộp | Có |
| eval / heldout (fixture) | 40 | `fixtures/t02_raw_qc/` | Theo `manifest.csv` của fixture | Có |
| dev (ảnh thật, **ngoài metric chính thức**) | 75 | `data/real/t02_traffic_125/` — Wikimedia Commons, giữ attribution local | Theo từng ảnh tại `attribution.csv`/catalog | Không |
| eval (ảnh thật, **ngoài metric chính thức**) | 50 | Cùng nguồn, seed 42 | Theo từng ảnh tại `attribution.csv`/catalog | Không |

- **Schema:** `image_id`, `path`, `camera_id`, `light`, `split`; QC types: `none`, `blur`, `glare`, `dark`, `compression`. `poor_quality` chỉ là **nhóm tìm kiếm ứng viên**, không phải class GT của T02.
- **Seed / split:** seed 42. Fixture: 96 ảnh 320×180 từ 24 cảnh gốc, split theo cảnh (56/40). Ảnh thật: 125/125 được chọn, dev/eval=75/50; **scene_group** vẫn cần kiểm thủ công để loại nguy cơ cùng cảnh lọt hai split.
- **Manifest:** lượt chạy ảnh thật kiểm SHA-256 **PASS** bằng `src.common.manifest.verify_manifest`; không tự suy ra mọi điều kiện license đều đã đạt.
- **GT:** chưa có GT T02 hợp lệ trong kết quả được nhóm cung cấp; nhãn thu thập của 125 ảnh là **candidate**, `labels_verified=false` và `can_claim_official_metrics=false`. Dữ liệu thật không được push công khai.

## 03 · Research & design

- **Tham khảo kỹ thuật (URL):** [đặc tả T02](../docs/tracks/T02.md) — review budget / evaluator; [OpenCV Laplace operator](https://docs.opencv.org/4.x/d5/db5/tutorial_laplace_operator.html) — nền tảng Laplacian baseline; [Wikimedia Commons licensing](https://commons.wikimedia.org/wiki/Commons:Licensing) — lưu ý provenance ảnh. Ngày lập báo cáo 15/11/2026; **ngày đọc độc lập của từng thành viên chưa xác minh**.
- **Flow:** `images + images.csv + manifest → SHA-256/schema check → Laplacian hoặc multi-signal QC → rank Top-20 → human review + audit → HOLD / REWORK / GO → reports`.
- **Baseline:** độ biến thiên Laplacian toàn ảnh, chọn threshold **phân vị 20% của dev**, `score=threshold−laplacian_variance`. Không dùng `eval` để chọn threshold.
- **PoC:** blur (Laplacian và sharpness chuẩn hóa tương phản), dark (thống kê độ sáng), glare (pixel bão hòa và patch), compression (gián đoạn biên khối 8×8). Calibrate trên `dev`; thiếu dev → báo lỗi, không fallback sang eval.
- **Offline:** Python/OpenCV, **không dùng weights/model tải từ mạng** khi chạy scoring; `--offline --seed 42`. Trade-off: baseline dễ kiểm chứng nhưng chỉ phát hiện blur; PoC đa tín hiệu nhưng nhạy với domain shift / metadata `unknown`.

## 04 · Baseline vs PoC

- **Baseline:** `src/t02/baseline.py`, tác giả TV2 (commits gốc `7612650`, `d5513ee`), Leader tích hợp `66936c9`.
- **PoC:** `src/t02/scoring.py`, tác giả TV3 (commit gốc `c5b75bf`), chỉnh dev-only và nhãn phân tích `59836e4`.
- **Protocol so sánh:** cùng fixture eval=40, review **B=20**, seed=42; khi có GT phải dùng **hai output official runner** và evaluator giống nhau. So sánh Top-20 trong CLI Core hiện là proxy ranking, **không thay thế** official baseline-vs-PoC evaluation.

**Bảng 1 · Baseline vs PoC & hard slices** (bảng chưa có `src.compare` vì chưa có GT/pair metrics):

| Metric (unit) | Baseline | PoC | Δ & chú thích |
|---|---|---|---|
| Primary: Defect Recall@20 (fraction, higher tốt) | **N/A — chưa đánh giá GT** | **N/A — chưa đánh giá GT** | N/A; không tính Δ |
| Precision@20 (fraction) | N/A | N/A | B=20; không gọi FP/FN khi thiếu GT |
| Hard slice: `cam_B` hoặc `night` (Recall@20) | N/A | N/A | N và GT theo slice chưa có |
| Runtime / 100 items (s) | N/A | N/A | Chưa benchmark chung máy / điều kiện; **25.4251 s** chỉ là tổng 1 lượt pipeline ảnh thật 125 ảnh, không phải phép so sánh |

**Quan sát không dùng GT:** chạy `python -m src.t02.scoring` trên fixture xếp hạng đủ 96 ảnh; Top-20 eval gồm compression=8, glare=4, blur=4, dark=4 theo **dự đoán của Core**. Baseline-only: `img_03_0`, `img_06_0`, `img_15_0`; Core-only: `img_01_3`, `img_05_3`, `img_13_2`. Đây là **khác biệt tập chọn**, không phải FP/FN thật.

## 05 · Evaluation protocol

- **Primary — Defect Recall@20** (đơn vị ảnh): `# ảnh có is_defect=1 trong Top-20 eval / # ảnh có is_defect=1 trong toàn bộ eval`. **Precision@20:** `# ảnh lỗi thật trong Top-20 eval / # ảnh được chọn`.
- **Ghép với GT:** bằng `image_id`, giới hạn cùng split `eval`. Pipeline scoring **không đọc GT**; evaluator được chạy tách biệt. Mẫu số 0 → báo N/A.
- **Threshold / budget:** ngưỡng baseline chọn trên dev 20th percentile; Core chỉ học reference từ dev. `B=20`, seed=42; **không tune lại sau khi nhìn nhãn eval**.
- **Bất định:** khi có GT cần báo N, số đếm thật và Wilson CI hoặc bootstrap theo đơn vị phù hợp. Hiện N/A vì chưa có GT được xác minh.
- **Lệnh đánh giá (chỉ chạy khi GT evaluator sẵn sàng):** `python -m src.evaluate --track t02 --pred out/baseline/ranked_review.csv --run-name baseline --out reports/metrics_baseline.json`; tương tự PoC dùng `out/poc/ranked_review.csv`, sau đó `python -m src.compare reports/metrics_baseline.json reports/metrics_poc.json --out reports/table1_baseline_vs_poc.md`.

## 06 · Result slices

| Slice | N | Baseline | PoC | Ghi chú |
|---|---:|---|---|---|
| `camera_id=cam_B` (fixture) | 32 ảnh toàn bộ fixture | N/A | N/A | Cần GT và N riêng của eval; optics mềm có thể bị báo mờ nhầm |
| `light=night` (fixture) | 20 ảnh toàn bộ fixture | N/A | N/A | Ảnh đêm có thể có Laplacian thấp dù vẫn hữu dụng |
| Ảnh thật, `light=unknown` | 125 ứng viên | N/A | N/A | Không suy đoán metadata / không được tính official metric |

- **Failure case 1:** `img_06_0` (`cam_B`, night, fixture) xuất hiện trong baseline-only Top-20; điểm thấp của Laplacian có thể phản ánh quang học và môi trường chứ chưa chắc blur. **Chưa kết luận là FP**.
- **Failure case 2:** `img_05_3` (cam_A, day, fixture) xuất hiện trong Core-only Top-20; Core giải thích bằng glare cục bộ, trong khi Laplacian toàn ảnh vẫn cao. **Chưa kết luận là FN**.
- **Failure/domain shift trên ảnh thật:** `DARK_025`, `BLUR_021`, `BLUR_024` đều được dự đoán **glare**, `local_patch250=1.00`, dù thuộc các nhóm ứng viên khác nhau; cần mở ảnh xem để xác nhận. `camera_id`/`light` unknown có thể hạn chế chuẩn hóa.
- **Latency/compute:** một lượt pipeline offline 125 ảnh thật **25.4251 s**, trên máy Windows của nhóm trưởng; chưa có benchmark CPU chuẩn hóa hoặc ms/item độc lập từng mô-đun.

## 07 · Human & decision

- **Review:** `out/poc_real/review_queue.csv`, budget B=20, xếp theo `score` giảm dần; `contact_sheet.html` offline.
- **Override:** reviewer quyết định approve/edit/reject/escalate, ghi `review_note` khi cần; lưu `review_results.csv` và `audit_log.jsonl`.
- **Decision thực tế:** `out/poc_real/decision.json`: `status=HOLD`, `reason_code=REVIEW_INCOMPLETE`, `owner=Pham Hai (Leader / Review Sign-off)`, `n_resolved=0`, `n_pending=20`. **20/20 gợi ý máy là RECAPTURE, không phải 20 quyết định con người**.
- **HOLD/REWORK:** không release khi còn review chưa giải quyết hoặc dữ liệu chưa đủ điều kiện; chỉ GO khi đã đủ bằng chứng theo chính sách của pipeline.

## 08 · Reproduce & tests

```powershell
# Chạy từ thư mục repo trên Windows, có .venv
.\.venv\Scripts\python.exe -m src.main --track t02 --pipeline src.t02.baseline --input fixtures/t02_raw_qc --config configs/lab.yaml --output out/baseline --offline --seed 42
.\.venv\Scripts\python.exe -m src.main --track t02 --input fixtures/t02_raw_qc --config configs/lab.yaml --output out/poc --offline --seed 42
.\.venv\Scripts\python.exe -m pytest -q -m "not requires_gt"
# Ảnh thật cần có sẵn dữ liệu local; không download lúc demo
powershell -ExecutionPolicy Bypass -File .\tools\t02_real\run_real_t02.ps1
```

- **Test gần nhất:** **71/71 PASS**, gồm 6 test QA tích hợp và 7 test chuẩn bị dữ liệu thật; command `pytest -q -m "not requires_gt"`. `requires_gt` không được tính trong 71.
- **Môi trường đã chạy:** PowerShell/Windows, Python từ `.venv`; phiên bản Python/CPU chưa được ghi nhận ở log người chạy — không tự điền.
- **Git:** mốc `main` sau merge/push là **`2460a8b`**. Real-data prepare: source 125, selected 125, dev 75/eval 50, SHA-256 PASS, `src.main` `status=0`.
- **Evaluator:** chỉ chạy khi có GT hợp lệ và ghi lại output thực tế; không dựng `reports/metrics_*.json` giả.

## 09 · Limitations & ethics

- Ảnh thật Commons cần TV4 xác minh `label_review.csv`, `scene_group`, từng license/attribution; nhãn ứng viên **không phải GT**. Không public ảnh thô nếu chưa xác nhận quyền và PII.
- Core trên ảnh thật có dấu hiệu **glare nhạy quá mức**; 5 ảnh thuộc nhóm ứng viên `NORM` cũng vào Top-20, nhưng **không kết luận sai** khi chưa có review xác thực.
- **Chưa có** Defect Recall@20, Precision@20, CI, metric slice và 20 quyết định human. Trạng thái HOLD là trung thực, không phải lỗi chương trình.
- Khi scale 10×: cần kiểm dedupe theo scene, chi phí CPU/review, data lineage và phân phối ánh sáng/camera. Không khẳng định tuân thủ GDPR hoặc luật Việt Nam chỉ qua checklist kỹ thuật; cần domain owner/DPO/legal xác nhận.

## 10 · Team contribution

**Bảng 2 · Individual contribution evidence** (xem thêm `reports/team_contributions.csv`):

| Học viên | Git author/email | Module / vai trò | Commit SHA / diff chứng minh | Trình bày? |
|---|---|---|---|---|
| **Phạm Hải** | `PHai237` / email chưa xác minh | Leader, integration, review/report | `66936c9`, `59836e4`, `338fca6`, `2460a8b`; `tools/t02_real/*`, `docs/T02_REAL_DATA.md` | Chưa phân công |
| **Phạm Việt Hoàng** | `hoang` / email chưa xác minh | Baseline + dữ liệu | `7612650`, `d5513ee`; `src/t02/baseline.py` | Chưa phân công |
| **Bùi Quốc Bình** | `binhbui8112004` / email chưa xác minh | Core Algorithm | `c5b75bf`; `src/t02/scoring.py` | Chưa phân công |
| **Thảo Linh** | `ThaoLinh0423` / email chưa xác minh | QA / Testing | `58fdab5`; `tests/test_t02_qa.py` | Chưa phân công |

**Attribution:** commit Leader khi tích hợp không thay thế quyền tác giả của phần việc TV2/TV3/TV4. Chỉ 4 người thuộc nhóm; không thêm thành viên thứ năm.

## 11 · References

| URL | Ngày xem | 1–2 dòng ý nghĩa |
|---|---|---|
| [docs/tracks/T02.md](../docs/tracks/T02.md) | 15/11/2026 (đối chiếu trong repo) | Yêu cầu 5 bước, metric Recall@20, hard slices và budget 20 |
| [docs/T02_REAL_DATA.md](../docs/T02_REAL_DATA.md) | 15/11/2026 (đối chiếu trong repo) | Quy trình manifest/nhãn verified, giới hạn đối với tập Commons |
| [OpenCV — Laplace](https://docs.opencv.org/4.x/d5/db5/tutorial_laplace_operator.html) | Ngày truy cập thành viên chưa xác minh | Tham khảo phương pháp đạo hàm ảnh / Laplacian |
| [Wikimedia Commons Licensing](https://commons.wikimedia.org/wiki/Commons:Licensing) | Ngày truy cập thành viên chưa xác minh | Cơ sở kiểm provenance và quyền sử dụng ảnh |

---

**Bảng 3 · Checklist chốt khi nộp**

- [x] Repo và code được push trên `main`; dữ liệu thật không được commit công khai.
- [x] Có lệnh chạy Baseline, PoC, test và data-real offline (cần thư mục dữ liệu local).
- [x] Có baseline/PoC, ≥2 failure case cần review, queue, decision/audit evidence.
- [x] Có nguồn/provenance, split, seed và ghi rõ thiếu GT verified.
- [x] Có bằng chứng commit cho **4** thành viên trong Bảng 2.
- [ ] **Chưa có** official GT metrics/`reports/table1_baseline_vs_poc.md` từ evaluator: **không khai báo giả**.
- [ ] **Chưa hoàn tất** human review 20 ảnh, decision hiện HOLD.
- [ ] Kiểm tra/nếu cần tạo tag `demo-180m`, `final-24h` và demo 3–5 slides theo hướng dẫn giảng viên.
- [ ] Họ tên đầy đủ của TV4, Git email, tên người trình bày cần xác nhận bổ sung.
