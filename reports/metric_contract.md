# Metric contract (khai báo bắt buộc — chốt ở phút 30, trước khi chạy eval)

> Các metric chuẩn đã được cài trong `src/metrics/tracks.py`. File này là nơi nhóm **cam kết** cách dùng chúng.
> Không đổi testset, threshold hay trọng số sau khi đã thấy kết quả eval.

> **BẢN NHÁP CHƯA CHỐT:** Threshold và trọng số của Baseline/PoC sẽ được nhóm xác nhận trước khi đánh giá trên tập eval.

| Mục | Khai báo của nhóm |
|---|---|
| Track | T02 — Raw QC Triage |
| Primary metric (tên đúng như evaluator in ra) | `Defect Recall@B` |
| Tăng tốt hay giảm tốt? | higher |
| Đơn vị đánh giá (image / region / pair / release / batch / case …) | image (`image_id`) trong split `eval` |
| Công thức + numerator / denominator | `TP@20 / N_defect_eval`: tử số = ảnh lỗi thật thuộc eval được xếp trong top 20 của eval; mẫu số = tổng ảnh `is_defect=1` của eval. Nếu không có GT thì không tính. |
| Cách ghép prediction ↔ GT (IoU? id? tolerance?) | Đối chiếu theo `image_id`; sort `score` giảm dần sau khi lọc `eval`; không dùng IoU. |
| Candidate pool cố định | 96 ảnh synthetic / 24 scenes: 56 ảnh dev (14 scenes) + 40 ảnh eval (10 scenes). Model xuất đủ 96 ảnh; evaluator lọc eval trước top-B. |
| Review budget B / K | B=20; review vận hành top 20/96, official eval top 20/40. |
| Seed | 42 |
| Threshold policy (chọn trên dev như thế nào) | Baseline: một ngưỡng Laplacian toàn ảnh, chọn trên dev. PoC: tham số **[TV3/Leader CHỐT trên dev trước eval; ghi công thức, giá trị, commit]**. Không tune eval. |
| Eval split (không dùng để tune) | `eval` (40 ảnh), không đọc `gt/` trong pipeline. |
| Chỉ số lỗi xấu (miss / false alarm / false reject) | Miss: ảnh lỗi không vào top B; false alarm: ảnh sạch vào top B; false recapture: ảnh dùng được bị yêu cầu chụp lại. |
| Slices sẽ báo cáo (≥2) | `light` (day/dusk/night); `defect_type` (nếu có GT); `camera_id` cho phân tích thủ công phụ. |
| Cách báo độ bất định khi N nhỏ (Wilson CI / bootstrap) | **[TV4 CHỐT, ví dụ Wilson CI hoặc bootstrap theo scene; chưa tính khi chưa có GT]**. Ghi N mẫu số. |
| Ngày giờ chốt + người chốt | **[CẦN ĐIỀN giờ VN + leader + commit SHA TRƯỚC eval]** |

Nếu baseline = 0 thì ghi rõ "baseline = 0" thay vì phần trăm cải thiện.

**Ghi chú:** `Precision@B = TP@20/20` và false alarm theo light là metric phụ. Dự đoán do pipeline tạo ra không phải GT. `gt/labels.csv` hiện do giảng viên giữ; không tự chế số `reports/metrics_*.json`.
