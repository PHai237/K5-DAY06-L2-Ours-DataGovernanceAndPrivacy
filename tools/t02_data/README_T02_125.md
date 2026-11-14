# T02 · Traffic 125 Collector (5 nhóm × 25 ảnh ứng viên)

Bộ công cụ **tìm nguồn ảnh chụp giao thông thật**, tải vào máy local, xuất metadata bản quyền và phát hiện ảnh trùng. Không dùng BDD100K hoặc dữ liệu instructor. Dữ liệu chỉ lấy từ **Wikimedia Commons**; script tự tìm kiếm bổ sung, không giới hạn 68 ứng viên cũ.

## Chuẩn bị

- Chạy PowerShell tại **gốc repo** `K5-DAY06-L2-Ours-DataGovernanceAndPrivacy`.
- Script cần Python trong `.venv` và `Pillow`, `numpy` (đều có trong `requirements.txt`).
- Internet để tìm/tải nguồn Commons. Script không cần Hugging Face token.
- **Không lưu ảnh thật lên GitHub public.** `.gitignore` hiện bỏ qua `data/real/` và `data/cache/`.

## A. Giải nén ZIP vào `tools/t02_data/` (branch riêng)

```powershell
New-Item -ItemType Directory -Force .\tools\t02_data | Out-Null
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\T02_Traffic_125_Collector.zip" -DestinationPath .\tools\t02_data -Force
```

## B. Tải 125 ứng viên mới, hạn chế dùng lại 50 ảnh cũ

```powershell
.\.venv\Scripts\python.exe .\tools\t02_data\fetch_traffic_125.py --skip-seeds --out .\data\real\t02_traffic_125 --per-group 25 --pause 1.2
```

Nếu nguồn Commons khó tìm đủ 25 ảnh cho mỗi nhóm, lệnh kết thúc với exit code 2, ghi rõ số lượng thực tế. Có thể **chạy lại chính lệnh trên** để tiếp tục; không xóa ảnh đã tải. Nếu chỉ muốn ưu tiên đủ số lượng và chấp nhận thử lại danh sách 68 ảnh đã tìm trước đó, bỏ `--skip-seeds` (sẽ chứa một phần ảnh từ đợt 50 cũ, chưa được xác nhận chất lượng).

Wikimedia có rate limit HTTP 429; tool đọc `Retry-After`, chờ và thử lại. Không dùng nhiều luồng hoặc thay IP để né giới hạn. Nếu cần, tăng `--pause 2.5` rồi chạy tiếp.

## C. Kiểm kê nhanh

```powershell
Get-Content .\data\real\t02_traffic_125\collection_log.json -Encoding utf8
( Get-ChildItem .\data\real\t02_traffic_125\images -File -Recurse | Measure-Object ).Count
Start-Process .\data\real\t02_traffic_125\contact_sheet.html
```

Kỳ vọng tối đa: `blur=25`, `glare=25`, `poor_quality=25`, `dark=25`, `normal=25`, tổng 125. Nếu con số thực tế thấp hơn, script ghi `complete_candidate_counts=false`.

Các kết quả sinh ra trong `data/real/t02_traffic_125/`:

- `images/` — file ảnh JPG/PNG đã tải, giữ tại máy cục bộ;
- `source_catalog.csv` — tên gốc, Commons URL, author, license, sha256, dHash/aHash, kết quả screening;
- `manifest.csv` — bảy cột provenance theo hợp đồng lab;
- `images.csv` — `image_id,path,camera_id,light,split`, với `camera_id/light=unknown`, `split=unassigned`;
- `label_review.csv` — **nhãn thật để trống**, người kiểm duyệt cần điền;
- `contact_sheet.html` — ảnh tải để duyệt trực quan;
- `collection_log.json` — số lượng, lỗi, trạng thái.

## D. Quan trọng: không báo cáo sai về nhãn

5 nhóm này là **nhóm ứng viên theo nguồn tìm kiếm**, KHÔNG phải ground truth. Thuật toán tìm kiếm ảnh không thể bảo đảm file đúng cảnh giao thông hoặc đủ nghiêm trọng để `RECAPTURE`. Cờ `LIKELY_CUE` cũng không chứng minh lỗi QC.

- `blur`: chụp bokeh nghệ thuật ≠ lỗi mờ camera cần recapture.
- `glare`: có mặt trời/đèn ≠ che mất thông tin quan trọng.
- `dark`: ảnh ban đêm nhưng rõ ≠ thiếu sáng nghiêm trọng.
- `poor_quality`: mưa, kính ướt, nhiễu ≠ tự động là `compression`. **T02 chỉ có `none, blur, glare, dark, compression`**; phải quyết định lại nhãn chuẩn khi QA.
- `normal`: cần chắc chắn đủ nét/ánh sáng/không lóa.

Trước khi đưa vào đánh giá: TV4 cần duyệt ảnh và nhãn, loại ảnh không đúng cảnh, gần trùng khó phát hiện, ảnh không đạt. Dùng `label_review.csv` và ghi rõ người duyệt. Đừng tạo nhãn từ tên thư mục rồi tính Recall/Precision.

Không chia các bản xử lý/phóng to của cùng ảnh gốc sang hai split dev/eval; giữ các bản cùng nguồn trong một nhóm. Split chỉ định sau khi xác minh và không tune trên eval. BDD/instructor synthetic vẫn là bộ chấm chính thức theo tài liệu lab.

## E. Push code để thành viên thứ 4 dùng

Đang trên branch `data/t02-traffic-tooling`:

```powershell
git add tools/t02_data/fetch_traffic_125.py tools/t02_data/candidate_sources.csv tools/t02_data/README_T02_125.md tools/t02_data/test_fetch_traffic_125.py
git diff --cached --stat
git diff --cached --check
git commit -m "feat(t02): add resumable 125-photo traffic dataset collector"
git push -u origin data/t02-traffic-tooling
```

**Không `git add -f data/real/` hay `data/cache/`.** Vì ảnh có thể chứa người/biển số thật, repo yêu cầu không đẩy dữ liệu thật lên public/cloud. Người thứ 4 tải tool từ branch rồi tự chạy trên máy họ, hoặc nhận ảnh qua kênh được giảng viên cho phép theo giấy phép và quy định bảo mật.

## F. Tự kiểm thử (không cần Internet)

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s .\tools\t02_data -p 'test_fetch_traffic_125.py' -v
```

Kiểm thử offline sử dụng ảnh giả sinh trong thư mục temp **chỉ để test tool**, không thuộc dataset bài lab.
