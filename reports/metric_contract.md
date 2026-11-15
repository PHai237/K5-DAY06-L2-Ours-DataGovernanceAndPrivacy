# Metric contract (khai báo bắt buộc — chốt ở phút 30, trước khi chạy eval)

> T02 — G02. Đây là **giao thức đo**, không phải số liệu từ evaluator. Không đổi threshold / testset sau khi xem eval.

| Mục | Khai báo của nhóm |
|---|---|
| Track | `t02` — Raw QC Triage |
| Primary metric (tên đúng như evaluator in ra) | Defect Recall@B (`B=20`; đối chiếu chính xác output evaluator khi có GT) |
| Tăng tốt hay giảm tốt? | Higher |
| Đơn vị đánh giá (image / region / pair / release / batch / case …) | image (`image_id`) |
| Công thức + numerator / denominator | `# ảnh is_defect=1 trong Top-20 eval / # ảnh is_defect=1 trong toàn eval`; mẫu số 0 → N/A |
| Cách ghép prediction ↔ GT (IoU? id? tolerance?) | `image_id` duy nhất, cùng `eval`; không dùng GT trong pipeline |
| Candidate pool cố định | `fixtures/t02_raw_qc` 96 ảnh (dev 56, eval 40); 125 ảnh thật chỉ demo, chưa GT |
| Review budget B / K | B=20 |
| Seed | 42 |
| Threshold policy (chọn trên dev như thế nào) | Baseline Laplacian quantile 0.20 trên dev; Core calibrate trên dev hoặc dùng reference mặc định có sẵn; thiếu dev phải lỗi |
| Eval split (không dùng để tune) | `eval` 40 ảnh fixture; không tune bằng nhãn eval |
| Chỉ số lỗi xấu (miss / false alarm / false reject) | Missed defect, non-defect trong Top-20; FP/FN chỉ xác nhận bằng GT |
| Slices sẽ báo cáo (≥2) | `camera_id` (`cam_A`, `cam_B`); `light` (`day`, `dusk`, `night`) |
| Cách báo độ bất định khi N nhỏ (Wilson CI / bootstrap) | Báo N và numerator/denominator; Wilson CI cho tỉ lệ khi có GT; hiện N/A |
| Ngày giờ chốt + người chốt | G02 / Phạm Hải; **chưa có log xác nhận mốc chốt phút 30**, không khẳng định đã freeze đúng hạn |

**Secondary:** Precision@20 = `# ảnh lỗi thật trong Top-20 eval / # ảnh được chọn`. **Không tính** official Recall/Precision từ nhãn candidate của 125 ảnh thật hoặc từ chênh lệch giữa hai top-k. `labels_verified=false`, current `HOLD/REVIEW_INCOMPLETE`.
