# T02 — Bằng chứng phần Leader: Human Review & Decision

> **Loại bằng chứng:** kiểm thử chức năng (smoke test), không phải đánh giá chất lượng thuật toán PoC. Bản ghi tóm tắt từ log chạy trên máy Leader ngày 14/11/2026. Không dùng số điểm random để tuyên bố Defect Recall@20 hay Precision@20.

## 1. Mục tiêu

Kiểm chứng luồng: kiểm tra đầu vào → nhận bảng điểm ảnh → lập danh sách top-B → người duyệt và sửa hành động → audit → quyết định GO/HOLD/REWORK. Thành viên 3 phụ trách thuật toán `src/t02/scoring.py`; thử nghiệm này dùng `src.examples.random_baseline` **chỉ để cấp điểm đầu vào**, rồi chạy lại luồng Leader qua `src.t02.review_from_csv`.

## 2. Môi trường và lệnh chạy lại

- Hệ điều hành: Windows; Python: 3.13.3; seed = 42; offline = true.
- Dữ liệu: `fixtures/t02_raw_qc/`, 96 ảnh; queue B=20.
- Kiểm tra môi trường: `python -m tools.preflight` → **0 FAIL, 2 WARN** (thiếu `data/real` và `models_optional`, đều tùy chọn).
- Kiểm thử: `python -m pytest -q` → **không có FAIL** (các test cần GT ẩn được skip).

```powershell
.\.venv\Scripts\python.exe -m src.main --track t02 --pipeline src.examples.random_baseline --config configs/t02_review_smoke.yaml --output out/leader_fixture_scores --offline --seed 42
.\.venv\Scripts\python.exe -m src.main --track t02 --pipeline src.t02.review_from_csv --config configs/t02_review_smoke.yaml --output out/leader_smoke --offline --seed 42
Start-Process .\out\leader_smoke\contact_sheet.html
```

Trong giao diện HTML, reviewer nhập tên, chọn quyết định cho một ảnh, ghi chú lý do và xuất CSV. Đặt file `review_queue_reviewed.csv` tại `out/leader_smoke/`, chạy lại lệnh thứ hai. Đây là quy trình thao tác bằng tay; không mô tả việc duyệt toàn bộ 20 ảnh nếu chưa thực hiện.

## 3. Bằng chứng quan sát từ log

- Run tạo điểm mẫu: `status=0`; chạy review đầu: `status=0`; chạy review sau khi nhập ghi chú: `status=0`.
- Ảnh `img_01_1`: `reviewer_decision=edit`, `override_value=KEEP`, `final_action=KEEP`; reviewer đã ghi lý do *Ảnh rõ ràng*.
- `review_results.csv`: ghi nhận **1 quyết định**, **1 ảnh đã giải quyết**, **19 ảnh còn chờ** trong queue 20 ảnh.
- `decision.json`: `status=HOLD`, `reason_code=REVIEW_INCOMPLETE`, `n_review_decisions=1`, `n_resolved=1`, `n_pending=19`, `n_recapture_confirmed=0`.
- `audit_log.jsonl`: có sự kiện `override:edit`, `review:edit` đối với `img_01_1` và `batch_decision` với trạng thái `HOLD`.
- Một lần chạy thử với `edit` nhưng thiếu `review_note` bị từ chối rõ ràng (`status=2`, thông báo cần lý do). Sau khi thêm lý do, cùng luồng chạy lại thành công (`status=0`).

**Giải thích:** trạng thái HOLD là đúng vì người duyệt chưa xử lý đủ B=20. Không được diễn giải HOLD là thất bại của mô hình chấm điểm, cũng không được diễn giải thao tác KEEP đơn lẻ là ảnh thực sự không lỗi theo ground truth.

## 4. Cơ chế kỹ thuật và giới hạn

- `src/pipeline.py`: điều phối 5 bước `load → process → rank → review → decide`.
- `src/t02/review_flow.py`: kiểm tra metadata/provenance, tính đầy đủ của bảng điểm; lập queue top-20, xuất HTML offline; kiểm tra CSV review, lý do và người duyệt; áp override; ghi audit và quyết định.
- Override **chỉ thay `pred_action`**, **không thay `score`**. Nhờ đó xếp hạng dùng để tính Defect Recall@B không bị thao tác người duyệt làm sai lệch.
- Logic quyết định cho *queue top-B*: chưa review đủ / có escalation → `HOLD`; review đủ, có ảnh `RECAPTURE` → `REWORK`; review đủ và tất cả `KEEP` → `GO`. `GO` **không có nghĩa cả bộ 96 ảnh đã được xác nhận sạch**.
- Test này dùng điểm random có seed, **không** phải baseline Laplacian bắt buộc, **không** phải PoC của thành viên 3 và **không** có nhãn GT chính thức.

## 5. Bằng chứng cần bổ sung trước khi nộp chính thức

- [ ] Chạy lại pipeline mặc định với thuật toán thật của thành viên 3, lưu lệnh và `run_info.json`.
- [ ] Thực hiện human review trên queue từ score PoC; lưu review CSV, audit, decision và screenshot đã kiểm tra quyền chia sẻ.
- [ ] Chạy lại preflight và pytest sau khi merge mọi đóng góp; lưu số test pass/skip/fail, CPU và commit cuối.
- [ ] Kiểm chứng baseline Laplacian và PoC trên cùng pool/split/seed/B; chỉ báo official metrics khi có GT được phép.
- [ ] Ghi rõ owner, group ID và tag nộp khi đã được chốt.

**Nguồn:** log PowerShell và `out/leader_smoke/decision.json`, `review_results.csv`, `audit_log.jsonl` do Leader cung cấp; mã nguồn `src/pipeline.py`, `src/t02/review_flow.py` trên nhánh `main` tại thời điểm kiểm tra.
