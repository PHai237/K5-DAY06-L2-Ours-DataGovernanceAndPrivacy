# Metric Contract — T02 Raw QC Triage

> Các metric chuẩn đã được cài trong `src/metrics/tracks.py::eval_t02`.
> Nhóm cam kết tuân thủ protocol đánh giá dưới đây, không thay đổi testset, threshold hay trọng số sau khi chạy eval.

| Mục | Khai báo cam kết của nhóm G02 |
|---|---|
| **Track** | **T02 · Raw QC Triage** (ảnh mờ, lóa, thiếu sáng, nén) |
| **Primary metric** | **Defect Recall@B** (với $B = 20$, trên split `eval`) |
| **Tăng tốt hay giảm tốt?** | `higher` (càng cao càng tốt) |
| **Đơn vị đánh giá** | `image` (từng ảnh đơn lẻ, kích thước $320 \times 180$) |
| **Công thức & Tử số / Mẫu số** | • **Defect Recall@B**: $\frac{\text{Số ảnh lỗi thật (GT) nằm trong Top-B}}{\text{Tổng số ảnh lỗi thật trong tập eval}}$ (Tử số: $\lvert \text{Top-B} \cap \text{GT}_{\text{defect}} \rvert$, Mẫu số: $\lvert \text{GT}_{\text{defect}} \rvert$)<br>• **Precision@B**: $\frac{\text{Số ảnh lỗi thật (GT) nằm trong Top-B}}{B}$ (Mẫu số: $B = 20$) |
| **Cách ghép prediction ↔ GT** | Khớp chính xác theo khóa duy nhất `image_id` (chuỗi định danh, ví dụ: `img_00_0`, `img_05_3`) |
| **Candidate pool cố định** | 40 ảnh thuộc split `eval` trong `fixtures/t02_raw_qc/images.csv` (từ 10 cảnh gốc độc lập với tập dev) |
| **Review budget $B$** | **$B = 20$** ảnh (ngân sách chuyên viên kiểm tra) |
| **Seed** | **42** (mặc định cho mọi bước sinh ngẫu nhiên, sắp xếp ổn định `mergesort`) |
| **Threshold policy** | Toàn bộ ngưỡng đặc trưng (ngưỡng Laplacian theo camera `cam_A`/`cam_B`, tham chiếu trung vị ánh sáng theo lát cắt `day`/`dusk`/`night`, ngưỡng lóa cửa sổ trượt `patch_250`, và ngưỡng nén JPEG 8×8) được **calibrate nghiêm ngặt trên split `dev` (56 ảnh)**. Tuyệt đối không dùng nhãn hay ảnh eval để tune. |
| **Eval split** | `eval` (40 ảnh, hoàn toàn giữ kín, không tune) |
| **Chỉ số lỗi xấu** | • **False Alarm (FP)** trong top-20: Cảnh ban đêm hoặc camera mềm bị phạt nhầm $\rightarrow$ lãng phí công sức reviewer.<br>• **Missed Defect (FN)**: Ảnh có lỗi lóa biển số/đèn hoặc nén vỡ bị bỏ lọt khỏi top-20. |
| **Lát cắt (Slices) báo cáo** | • **Lát cắt ánh sáng (`light`)**: `day` (24 ảnh eval), `dusk` (8 ảnh eval), `night` (8 ảnh eval).<br>• **Lát cắt thiết bị (`camera_id`)**: `cam_A` (28 ảnh eval), `cam_B` (12 ảnh eval - quang học mềm). |
| **Độ bất định khi $N$ nhỏ** | Wilson score 95% Confidence Interval (CI) cho tỷ lệ Recall/Precision và Bootstrap empirical 1,000 lần. |
| **Ngày giờ chốt + Người chốt** | 2026-11-15 01:00 (giờ VN) · Pham Hai (Leader) & QA/Report Lead (Member 4) |

---

### Ghi chú bổ sung
1. **Baseline công bằng**: Baseline toàn ảnh sử dụng cùng budget $B=20$, cùng split `eval` (40 ảnh), cùng seed `42`. Ngưỡng baseline Laplacian được tính bằng phân vị 20% trên tập `dev` (186.97).
2. **Ground Truth bảo mật**: Repo học viên không chứa thư mục `fixtures/t02_raw_qc/gt/`. Đánh giá chính thức sẽ do giảng viên thực hiện qua overlay GT ẩn. Đánh giá nội bộ của nhóm thực hiện qua so sánh phân bổ đa đặc trưng và kiểm chứng chi tiết các failure modes.
