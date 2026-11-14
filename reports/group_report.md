# Group Report — Day 06 Data Lab (Field-to-Release PoC)

> **BẢN NHÁP CHƯA NỘP.** Giữ khung mục 00–11, Bảng 1–3 theo mẫu gốc. Kết quả chưa có GT chính thức để trống, không tự tạo số liệu. **Mẫu yêu cầu 3–5 trang**: kiểm tra độ dài bản hoàn chỉnh khi xuất/in.

## 00 · Header

| Mục | Giá trị |
|---|---|
| Group ID | **[CẦN ĐIỀN mã nhóm chính thức]** |
| Challenge | T02 · Raw QC Triage (blur, glare, dark, compression) |
| Thành viên (5–6) + vai trò | Nhóm **4 người**: 1. [Tên Leader] (Integration + Review); 2. [Tên TV2] (Data/Baseline); 3. [Tên TV3] (Core Algorithm); 4. [Tên TV4] (QA/Report). **Cần xác nhận giảng viên chấp nhận 4 người**. |
| Git URL | https://github.com/PHai237/K5-DAY06-L2-Ours-DataGovernanceAndPrivacy |
| Tag `demo-180m` (commit) | **[CHƯA XÁC NHẬN; chỉ điền nếu tag thực sự tồn tại]** |
| Tag `final-24h` (commit) | **[CHƯA XÁC NHẬN; chỉ điền khi hoàn tất và tạo tag]** |
| Deadline (giờ VN) | **[CẦN XEM LMS/thông báo của giảng viên]** |

## 01 · Problem statement

- **Ai bị ảnh hưởng:** người kiểm soát chất lượng dữ liệu, người vận hành camera, các hệ thống CV dùng ảnh đầu vào.
- **Điểm nghẽn:** nhiều ảnh ở ánh sáng/camera khác nhau; review toàn bộ tốn thời gian, còn lọc tự động một chỉ số dễ loại nhầm ảnh đêm hữu ích hoặc bỏ sót lóa cục bộ.
- **Đầu vào → đầu ra:** `images/*.jpg`, `images.csv`, `manifest.csv` → `ranked_review.csv` (`image_id,score`, score càng cao càng nghi lỗi) → `review_queue.csv` (20 ảnh) + `contact_sheet.html` → `review_results.csv`, audit và decision.
- **GO/HOLD/REWORK (policy hiện có trong code Leader):** chưa review đủ hoặc escalation → `HOLD`; đủ 20 và có RECAPTURE → `REWORK`; đủ 20 và đều KEEP → `GO`. **GO chỉ phản ánh queue 20 ảnh đã được review, không bảo đảm 96 ảnh đều sạch.**
- **Giả định cần người phụ trách xác nhận:** định nghĩa ảnh đủ chất lượng, chi phí recapture, ngưỡng vận hành và người ký duyệt chính thức **[CẦN ĐIỀN]**.

## 02 · Data & provenance

| Split | N | Nguồn / link | License | Synthetic? |
|---|---|---|---|---|
| dev | **56 ảnh / 14 cảnh** | `fixtures/t02_raw_qc/images.csv` + `images/` | CC0-1.0 | Có |
| eval / heldout | **40 ảnh / 10 cảnh** | Cùng nguồn, split `eval` | CC0-1.0 | Có |

- **Schema & class mapping:** input: `image_id,path,camera_id,light,split`. GT ẩn: `defect_type={none,blur,glare,dark,compression}`, `is_defect`, severity 0–2; pipeline không đọc `gt/`. Tổng: 96 ảnh từ 24 cảnh (320×180 theo handout), day=56/dusk=20/night=20, cam_A=64/cam_B=32.
- **Seed:** 42; tách dev/eval theo cảnh gốc, không trùng scene (đã đối chiếu dữ liệu fixture).
- **`manifest.csv` verified (sha256):** Log máy Leader trước đây `preflight: 0 FAIL, 2 WARN` (hai WARN do real data/model tùy chọn). **[CẦN CHẠY LẠI `python -m tools.verify_manifests` tại commit nộp cuối và lưu log]**.
- **Dữ liệu thật:** chưa sử dụng. Repo học viên không có GT ẩn; không tính official recall/precision khi chưa có GT hợp lệ.

## 03 · Research & design

- **2–3 references:** **[TV2/TV3 ghi URL, ngày xem và lý do thực sự chọn kỹ thuật; chưa điền khi chưa tham khảo]**.
- **Data flow:** `src.main` → verify manifest + load metadata → `src/t02/scoring.py::score_images` → kiểm tra đủ 96 score → xếp top 20 → HTML review offline → CSV override → audit log → quyết định với `reason_code`/`owner` → kết quả/báo cáo.
- **Offline:** CPU/Python, seed 42, offline guard; **[TV3 xác nhận model/weights/checksum/license nếu có; nếu không dùng thì ghi rõ không có pretrained weights]**.
- **Trade-offs:** Laplacian đơn giản nhưng nhạy với đêm và khác biệt quang học; PoC nhiều feature/ROI phức tạp hơn. **[TV2/TV3 bổ sung các lựa chọn thực tế và thông số đã chốt]**.

## 04 · Baseline vs PoC

- **Baseline (version/config/commit):** global Laplacian variance với **một ngưỡng duy nhất**, chọn trên dev; **[TV2 điền thuật toán thực thi, ngưỡng, commit và đường dẫn output]**. Ví dụ random có sẵn **không** phải baseline hợp lệ của T02.
- **PoC:** **[TV3 điền công thức, weights/threshold, commit, cấu hình và runtime đo thật]**.
- **Cùng pool/heldout/seed:** mục tiêu **96 ảnh dự đoán, eval 40, B=20, seed=42**; **[TV4 xác nhận từ hai lượt chạy thật trước khi đánh dấu hoàn tất]**.

**Bảng 1 · Baseline vs PoC & hard slices** — chỉ dán bảng từ `python -m src.compare reports/metrics_baseline.json reports/metrics_poc.json` sau khi hai file metrics được script tạo trên GT hợp lệ.

| Metric (unit) | Baseline | PoC | Δ & chú thích |
|---|---|---|---|
| Primary: Defect Recall@B | **Chưa có GT** | **Chưa có GT** | Chỉ tính bằng evaluator; higher better |
| Hard-slice: false alarm by light | **Chưa có GT** | **Chưa có GT** | N eval/slice phải do evaluator xác định |
| Review@B / miss / FP | **Chưa có GT** | **Chưa có GT** | B=20; Precision@B báo riêng |
| Runtime / 100 items | **[CHỜ script]** | **[CHỜ script]** | Chỉ điền số đo thật và thông số CPU |

## 05 · Evaluation protocol

- **Primary:** `Defect Recall@B = số ảnh is_defect=1 trong top B của split eval / tổng ảnh lỗi thật của eval`; đơn vị image_id. Secondary: Precision@B (TP@20/20), false alarm theo `light`, type accuracy khi có GT. Không tự gán nhãn eval.
- **Threshold / B / thời điểm chốt:** B=20; baseline chỉ chọn threshold trên dev; PoC **[TV3 ghi weights/threshold]**; ngày giờ/commit chốt **[CẦN ĐIỀN TRƯỚC EVAL]**.
- **Độ bất định:** **[TV4 chọn và giải thích Wilson CI hoặc bootstrap theo scene; chưa có kết quả CI]**.
- **Lệnh evaluate:** `python -m src.evaluate --track t02 --pred out/poc/ranked_review.csv --run-name poc --out reports/metrics_poc.json` (chỉ khi có overlay GT hợp lệ).
- **Hai top-20 khác nhau:** dashboard review lấy top 20 trên cả 96 ảnh; evaluator lọc 40 ảnh eval trước rồi mới lấy top 20. Không so lẫn hai danh sách.

## 06 · Result slices

| Slice | N | Baseline | PoC | Ghi chú |
|---|---|---|---|---|
| `light=day/dusk/night` | **[N eval từng slice: chờ script]** | [CHỜ GT] | [CHỜ GT] | Full-pool lần lượt 56/20/20, KHÔNG phải N eval |
| `camera_id=cam_A/cam_B` | **[N eval: chờ script]** | [CHỜ] | [CHỜ] | Slice bổ sung nếu script thực sự tính |

- **Failure case 1:** **[TV2/TV3 cung cấp ảnh đêm vẫn hữu ích nhưng bị xếp nhầm, image_id, score, hình, nguyên nhân]**.
- **Failure case 2:** **[TV3 cung cấp glare cục bộ bị bỏ qua hoặc cam_B bị báo mờ, kèm evidence]**.
- **Latency / compute:** **[TV4 đo ms/image và trích máy/CPU từ run_info.json; không dùng thời gian random smoke]**.

## 07 · Human & decision

- **Review queue:** `out/poc/review_queue.csv`, top B=20 score cao nhất của pool 96 ảnh; `contact_sheet.html` cho con người xem ảnh offline.
- **Override + audit:** file `review_queue_reviewed.csv` từ HTML, `edit/reject` phải có `override_value∈{KEEP,RECAPTURE}` và lý do, ghi `audit_log.jsonl`; sửa `pred_action`, **không sửa score**.
- **Decision policy + reason_code + owner:** incomplete → `HOLD/REVIEW_INCOMPLETE`; đủ review, có RECAPTURE → `REWORK/RECAPTURE_REQUIRED`; đủ và tất cả KEEP → `GO/REVIEWED_QUEUE_KEEP`. Owner **[CẦN xác nhận trong configs/lab.yaml]**.
- **Minh chứng hiện tại:** smoke test dùng điểm *random*, reviewer đổi `img_01_1` thành KEEP, ghi log, 1/20 ảnh đã duyệt → `HOLD`. **Đây chỉ là test chức năng, KHÔNG chứng minh chất lượng thuật toán**. **[Leader cần review với điểm PoC thật và cung cấp file/screenshot đã kiểm duyệt]**.
Minh chứng kiểm thử chức năng Human-in-the-Loop được lưu tại reports/t02_leader_evidence.md. Đây là smoke test sử dụng điểm random để kiểm tra review, override, audit và decision; chưa phải kết quả đánh giá thuật toán PoC chính thức.

## 08 · Reproduce & tests

```bash
python -m tools.preflight
python -m pytest -q
python -m src.main --input fixtures/t02_raw_qc --config configs/lab.yaml --output out/poc --offline --seed 42
python -m src.evaluate --track t02 --pred out/poc/ranked_review.csv --out reports/metrics_poc.json  # chỉ khi có GT hợp lệ
```

- **Output pytest:** log trước đây: không FAIL, test GT được skip. **[Chạy lại sau khi TV3 merge; `tests/test_cli.py` đang đòi exit=3 cho stub, cần sửa test khi Core triển khai]**.
- **Máy/CPU/OS/Python:** Windows, Python 3.13.3 (Leader); CPU **[CẦN TRÍCH run_info.json]**; commit cuối **[CẦN ĐIỀN]**.

## 09 · Limitations & ethics

- **PII/license:** synthetic CC0-1.0; không commit data/real, GT ẩn, thông tin cá nhân reviewer hoặc key lên repo công khai khi chưa có phép.
- **False alarms/scale 10×:** ảnh night và optics cam_B có thể lệch; đánh giá lại threshold, chi phí review, latency và số lượng ảnh ngoài domain.
- **Pháp lý:** không khẳng định tuân thủ GDPR/luật Việt Nam chỉ dựa trên pipeline; cần người có thẩm quyền xác nhận giả định.
- **Cải tiến:** chuẩn hóa theo camera/light, ROI glare, bổ sung dữ liệu thật có quyền và đánh giá theo scene.
- **Khai báo GenAI:** nhóm đã dùng ChatGPT hỗ trợ giải thích yêu cầu, Git/debug, tạo bản nháp code Leader và báo cáo; thành viên phải xác minh, hiểu và điều chỉnh sản phẩm. **[Liệt kê thêm công cụ, prompt và phần sử dụng thực tế; xác nhận quy định/AIAS từ giảng viên trước khi nộp]**.

## 10 · Team contribution

**Bảng 2 · Individual contribution evidence** (đối chiếu với `git shortlog -sne --all` và `reports/team_contributions.csv`)

| Học viên | Git author/email | Module / vai trò | Commit SHA / diff chứng minh | Trình bày? |
|---|---|---|---|---|
| **[Tên Leader]** | `PHai237` / **[xác nhận email Git]** | Integration/Review/Audit | `96ba65b`, `00bfc7d` | [CẦN ĐIỀN] |
| **[Tên TV2]** | [CHỜ COMMIT] | Data / Laplacian baseline | [CHỜ] | [CẦN ĐIỀN] |
| **[Tên TV3]** | [CHỜ COMMIT] | Core Algorithm | [CHỜ] | [CẦN ĐIỀN] |
| **[Tên TV4]** | [CHỜ COMMIT] | QA/Metric/Report | [CHỜ] | [CẦN ĐIỀN] |

## 11 · References

| URL | Ngày xem | 1–2 dòng ý nghĩa (không chép nguyên văn) |
|---|---|---|
| `docs/tracks/T02.md` | 14/11/2026 | Output, baseline và failure modes của T02 |
| `src/metrics/tracks.py::eval_t02` | 14/11/2026 | Metric evaluator và cách chọn top-B eval |
| https://policy.vinuni.edu.vn/all-policies/guidelines-on-student-use-of-generative-artificial-intelligence/ | 14/11/2026 | Quy định về AI disclosure và kiểm chứng; không xác định AIAS cho Day 6 |
| **[TV2/TV3 cần 2–3 nguồn nghiên cứu ngoài, ngày xem và ứng dụng thật]** | [CHỜ] | [CHỜ] |

---

**Bảng 3 · Checklist chốt khi nộp**

- [ ] Link repo và tag cuối cùng trong README; input mẫu không chứa PII thật.
- [ ] Đúng 1 lệnh run, 1 lệnh evaluate (khi có GT), 1 lệnh tests; không cần download khi chạy.
- [ ] Có baseline/PoC metrics **nếu GT được cung cấp**, ≥1 failure case, reviewer evidence, decision log; nêu minh bạch phần không khả dụng.
- [ ] Có license/source provenance, data splits, seed, offline environment, GT/eval N.
- [ ] Mỗi thành viên có ≥1 commit thực chất và được nêu minh bạch trong bảng trên.
