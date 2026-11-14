# T02 – Data Exploration & Laplacian Baseline

## 1. Mục tiêu

Khảo sát dữ liệu đầu vào của T02 Raw QC Triage, kiểm tra tính toàn vẹn dữ liệu và xây dựng thuật toán baseline phát hiện ảnh mờ bằng Laplacian Variance.

## 2. Khảo sát dữ liệu

Dữ liệu được cung cấp trong thư mục `fixtures/t02_raw_qc/`.

| Tiêu chí | Kết quả |
|---|---|
| Tổng số ảnh | 96 |
| Kích thước | 320 × 180 pixel |
| Tập dev | 56 ảnh |
| Tập eval | 40 ảnh |
| Camera A | 64 ảnh |
| Camera B | 32 ảnh |
| Ban ngày | 56 ảnh |
| Ban đêm | 20 ảnh |
| Hoàng hôn | 20 ảnh |
| Trùng image_id | 0 |
| Trùng đường dẫn | 0 |
| Thiếu metadata | 0 |
| Ảnh thiếu hoặc không đọc được | 0 |

## 3. Kiểm tra tính toàn vẹn dữ liệu

Sử dụng SHA256 để đối chiếu với `manifest.csv`.

Kết quả: 97/97 bản ghi hợp lệ, gồm 96 ảnh và một file `images.csv`.

File `images.csv` có sự khác biệt ký tự xuống dòng do Git trên Windows chuyển LF thành CRLF. Sau khi chuẩn hóa về LF để tính hash, kết quả khớp với manifest.

Các file ảnh được kiểm tra trực tiếp theo byte gốc, không thay đổi dữ liệu đầu vào.

## 4. Thuật toán baseline

Sử dụng OpenCV để tính Laplacian Variance nhằm ước lượng mức độ sắc nét của ảnh.

- Laplacian Variance thấp: ảnh có khả năng bị mờ.
- Laplacian Variance cao: ảnh có nhiều chi tiết hoặc đường biên rõ nét.
- Chọn một ngưỡng chung bằng phân vị 20% của Laplacian Variance trên tập dev.
- Không sử dụng tập eval để lựa chọn ngưỡng.
- Tính điểm nghi ngờ theo công thức:

`score = threshold - laplacian_variance`

Ảnh có score càng cao được ưu tiên kiểm tra trước.

## 5. Kết quả thực nghiệm

- Tổng ảnh xử lý: 96.
- Ngưỡng Laplacian: 187.0095.
- Số ảnh dự đoán mờ: 18.
- Số ảnh được đưa vào danh sách ưu tiên review: 20.
- File thống kê: `out/baseline/image_statistics.csv`.
- File xếp hạng: `out/baseline/ranked_review.csv`.

Chưa xác định Recall@20 hoặc Precision@20 vì chưa có nhãn đánh giá hợp lệ để đối chiếu.

## 6. Hạn chế

- Baseline chủ yếu phát hiện ảnh mờ, chưa đánh giá đầy đủ lỗi lóa và thiếu sáng.
- Ảnh ban đêm ít chi tiết có thể bị đánh giá nhầm là ảnh mờ.
- Ngưỡng chung có thể chưa phù hợp với các camera khác nhau.
- Ngưỡng phân vị 20% là lựa chọn thử nghiệm, chưa được xác nhận là tối ưu.

## 7. Kết luận

Đã hoàn thành khảo sát 96 ảnh, kiểm tra tính toàn vẹn dữ liệu và xây dựng baseline Laplacian Variance.

Kết quả baseline được dùng làm mốc tham chiếu để nhóm phát triển và so sánh với thuật toán PoC cải tiến.