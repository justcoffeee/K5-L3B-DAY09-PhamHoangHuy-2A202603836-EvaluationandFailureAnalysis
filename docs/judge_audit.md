# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (backend replay, không tốn API key).

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.8 | **có** | **dùng** được làm tín hiệu phụ (không phải cổng release) |
| helpful | 100 | 0.375 | 1.0 | 0.3 | **không** (κ, R) | **loại** — không được dùng làm gate |

Ma trận nhầm lẫn (FAIL là lớp dương):

- tone_ok: `tp=24, fp=4, fn=6, tn=66`; fail rate quan sát 0.28 → Rogan-Gladen hiệu chỉnh 0.30.
- helpful: `tp=9, fp=0, fn=21, tn=70`; fail rate quan sát 0.09 → hiệu chỉnh 0.30.

## ≥5 case audit thủ công

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS | FAIL | **Người** | Judge chỉ thấy từ lịch sự, bỏ qua đại từ "em/anh" và "nha" quá suồng sã với khách. Thêm luật: cấm tự xưng "em", cấm "nha/check giúp em" trong reply CSKH |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ cho đơn O-606 rồi nha." | PASS | FAIL | **Người** | Gọi khách lớn tuổi là "bạn" + "nha". Rubric phải chấm **cặp đại từ** (anh/chị vs em/bạn), không chỉ từ cảm thán |
| 3 | H-029 "Dạ, vui lòng chờ. Hệ thống đang xử lý, không cần nhắn thêm." | PASS | FAIL | **Người** | "Dạ, vui lòng" làm judge qua, nhưng "không cần nhắn thêm" là giọng ra lệnh. Thêm tiêu chí: không được từ chối nhận hỗ trợ |
| 4 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | **Người** | Judge phạt vì "thiếu lời xin lỗi" — rubric chưa tách *tone* khỏi *nội dung*. Bỏ yêu cầu xin lỗi bắt buộc; chỉ phạt khi khách đang khiếu nại nặng |
| 5 | H-051 "Dạ, LogiX đã refund 90.000đ cho đơn O-202 ạ." | FAIL | PASS | **Người** | Judge phạt vì từ tiếng Anh "refund" dù CS LogiX cho phép. Thêm allowlist thuật ngữ nội bộ (refund, shop, đơn) |
| 6 | H-063 "Dạ, LogiX đã hoàn 20.000đ và sẽ hoàn thêm cho anh/chị ạ." | PASS | FAIL | **Người** | Judge không đối chiếu được với ledger nên không thấy lời hứa ngoài hệ thống. **Đây là lý do tiền phải chấm bằng code** (`reply_ledger_match`), không giao cho judge |
| 7 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn theo chính sách hiện hành ạ." | FAIL | PASS | **Judge** | Nhãn người sai (đọc nhầm ticket): câu này đúng tone. Sửa `human=PASS` trong file nhãn, ghi lại lý do |
| 8 | H-094 "Da, LogiX da hoan 40.000đ cho don O-341, xin loi vi su bat tien." | PASS | FAIL | **Người** | Mất dấu tiếng Việt (dịch máy) — judge coi là "thân thiện". Thêm luật: reply phải giữ dấu tiếng Việt |
| 9 | HL-015 "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." | PASS | FAIL | **Người** | Nhãn `human_failure="sai tiền"`: helpful judge chỉ chấm độ lễ phép nên không bao giờ bắt sai số tiền → recall 0.3 |
| 10 | HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | **Người** | Sai xưng hô + không nêu số tiền; judge vẫn PASS vì câu ngắn, "lịch sự" |

## Kết luận

- **tone_ok**: dùng được (κ 0.757, P 0.857, R 0.8). Là tín hiệu *phụ*: nó đo cách nói, không đo tính đúng. Vẫn còn 4 false positive (H-008/H-017/H-029/H-094) → chỉ dùng để cảnh báo, không chặn merge.
- **helpful**: **loại**. Precision 1.0 nhưng recall 0.3 và κ 0.375: judge chỉ bắt được 9/30 ca fail thật, bỏ sót toàn bộ nhóm "sai tiền" (17 ca) và "sai xưng hô" (3 ca). Một gate dùng judge này sẽ cho qua đúng những lỗi đắt nhất — tiền. Vì vậy các metric tiền (`refund_amount_correct`, `reply_ledger_match`) chấm bằng code, judge helpful không xuất hiện trong `config/metric_spec.yaml`.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai; cần nhãn người mới để có held-out thật.
