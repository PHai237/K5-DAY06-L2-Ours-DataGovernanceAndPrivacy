# T02 — Quy trình thao tác chính xác cho nhóm 4 người (PowerShell)

> Đây là checklist vận hành, không phải kết quả đánh giá hay giấy phép dùng AI. Tham khảo `README.md`, `docs/tracks/T02.md`, `docs/T02_TEAM_INTEGRATION.md`, và chính sách VinUni. 14/11/2026.

## Bước 0. Xin xác nhận AIAS + nhóm 4 người

Repo T02 không nêu cấm ChatGPT; nhưng VinUni quy định giảng viên quyết định mức AI được phép cho assessment; khi dùng phải khai báo. Trước khi dùng bản nháp AI để nộp, hỏi coach: (a) AIAS Level nào/những việc được phép; (b) format khai báo công cụ/prompts; (c) nhóm 4 thay vì mẫu 5–6; (d) official metrics dùng overlay GT của giảng viên ra sao.

## Bước 1. Chuẩn bị branch báo cáo mới

```powershell
git switch main
git pull --ff-only origin main
git status -sb
git switch -c docs/t02-report-prep
```

Nếu `git status` có thay đổi bạn cần giữ, KHÔNG ghi đè file trước khi backup. Giải nén ZIP này vào root repo (nó bao gồm `reports/` và `docs/`, các file báo cáo mẫu được thay bằng **bản nháp**). Kiểm tra:

```powershell
git status --short
git diff -- reports/group_report.md reports/metric_contract.md reports/team_contributions.csv
```

## Bước 2. Leader điền dữ liệu đúng

Trong `reports/group_report.md`, điền mã nhóm, tên bốn thành viên, deadline LMS, sign-off. Kiểm tra `reports/team_contributions.csv`: lấy git author/email & full SHAs **thật** từ lệnh:

```powershell
git log b0ce8bfd..main --format="%H | %an | %ae | %s"
```

Trong `configs/lab.yaml`, đổi `group_id: G00` và `owner: TODO...` thành thông tin nhóm/người ký duyệt thật. Giữ `track: t02`, `seed: 42`, `offline: true`, `strict_provenance: true`. Chốt policy review trước khi nhìn eval.

## Bước 3. Thành viên 2: baseline

Tạo `src/t02/baseline.py`; dùng `src/common/image_ops.py::laplacian_variance`; ngưỡng một giá trị duy nhất chọn trên dev; score cao nghĩa nghi lỗi; tạo full `ranked_review.csv` cùng B=20/seed=42; lưu runtime. Ghi rõ threshold, commit, N và failure mode; báo thành viên QA cách chạy `--pipeline src.t02.baseline` nếu module có `run(ctx)`.

## Bước 4. Thành viên 3: thuật toán chính

Chỉ sửa `src/t02/scoring.py::score_images(ctx, images)` theo hợp đồng ở `docs/T02_TEAM_INTEGRATION.md`:

- Trả đủ **96** dòng `image_id`, `score` hữu hạn, ID không trùng; `score` càng cao càng nghi lỗi.
- Nên thêm `pred_defect_type` / `pred_action` (`KEEP`/`RECAPTURE`) / `reason`.
- Không đọc `gt/`, không tune eval, không sửa `src/pipeline.py`.

## Bước 5. Thành viên 4: tests & đánh giá

Tạo >=2 bài test thật (success + edge/failure), mở rộng slice analysis. **Khi thuật toán chính xong**, sửa `tests/test_cli.py::test_template_pipeline_fails_clearly_not_silently` vì test starter đang đòi `exit code 3`; phiên bản hoàn thiện cần `exit code 0`.

Metrics contract đã có draft, QA chốt threshold/slices/mẫu số/độ bất định và ghi lại lúc freeze.

## Bước 6. Leader review PR và tích hợp **trong repo nhóm**, không merge về VinUni

Mỗi thành viên: `git switch main; git pull --ff-only origin main; git switch -c feature/<ten-task>` -> code -> `git add <files>; git commit -m "..."; git push -u origin feature/<ten-task>`. Tạo PR mà **base repository** là `PHai237/K5-DAY06-L2-Ours-DataGovernanceAndPrivacy`, **base branch** `main`.

Chỉ merge khi đã xem file thay đổi, pass test và không ghi đè module khác.

## Bước 7. Kiểm thử E2E sau khi core + baseline có thật

```powershell
git switch main
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m tools.preflight
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m src.main --input fixtures/t02_raw_qc --config configs/lab.yaml --output out/poc --offline --seed 42
Start-Process .\out\poc\contact_sheet.html
```

Reviewer làm 20 ảnh thật từ score của PoC; export reviewed CSV vào `out/poc/review_queue_reviewed.csv`, chạy lại lệnh `src.main`. Xác minh `ranked_review.csv`, `review_results.csv`, `audit_log.jsonl`, `decision.json`, `decision_log.csv`, `run_info.json` (exit status=0). Quyết định `HOLD` khi queue còn pending là bình thường. **Không dùng random smoke làm kết quả PoC.**

## Bước 8. Chạy baseline và đánh giá

```powershell
.\.venv\Scripts\python.exe -m src.main --track t02 --pipeline src.t02.baseline --output out/baseline --run-name baseline --offline --seed 42
```

Nếu `baseline.py` không expose `run(ctx)`, điều chỉnh cách gọi dựa trên code THẬT của TV2. Repo học viên không có `fixtures/t02_raw_qc/gt/labels.csv`, nên KHÔNG có official Defect Recall@20 và Precision@20. Khi được giảng viên cấp GT hợp lệ, chạy các lệnh trong `reports/metric_contract.md` và tạo bảng `src.compare` **bằng script**, không chỉnh số thủ công.

## Bước 9. Đóng gói và nộp

Chép minh chứng đã **kiểm duyệt PII** từ `out/poc/` sang `reports/`/`demo/` theo `reports/README.md`; lưu các file config và commit SHA; thêm 2–3 nguồn nghiên cứu thực đọc; tạo slide 3–5 trang; xác nhận đủ 4 người có commit thật.

```powershell
git log b0ce8bfd..main --format="%h %an <%ae> %s"
git status --short
```

Để nộp bản final, tag theo mốc **thật** của giảng viên (không gắn sai tên/mốc):

```powershell
git tag final-24h
git push origin final-24h
```

**Chỉ tag khi đã chốt bản cuối**, kiểm tra mọi file nộp thật sự được commit và biết chính xác deadline LMS. Dùng branch báo cáo riêng để người khác review trước khi merge.

## Kiểm định form (đã đối chiếu lại template gốc)

- `reports/group_report.md`: đúng 12 mục `00–11`, đúng tiêu đề từng mục và Bảng 1–3; khi hoàn thiện cần giữ 3–5 trang.
- `reports/metric_contract.md`: đúng tên 15 trường ở template gốc; phải ký chốt ngưỡng/trọng số trước eval.
- `reports/team_contributions.csv`: đúng 8 cột, 4 dòng cho 4 người, **nhóm 4 cần giảng viên xác nhận vì template 5–6**.
- Không nộp nguyên bản nháp có dấu `[CHỜ]`, `[CẦN]`; không thay số metric bằng số đo smoke/random.
- Trong `reports/README.md`, file `review_queue.csv` minh chứng cần có reviewer/decision. `out/poc/review_queue.csv` chưa có review; phải lấy từ CSV reviewer export hoặc bảng đã ghép review, rồi lưu đúng tên và giữ audit.
- Trước khi nộp xem lại LMS, tag và tính hợp lệ khi dùng GenAI theo quy định giảng viên.
