# Trace case: từ trace tới quyết định sai đầu tiên

## Case: `seeded_regression` C-002@11 — ticket nói 5 ngày, order ghi 2 ngày

Chạy lại:

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, report `reports/eval_seeded_regression.json` (rows `item_id=E-002`, `seed=11`, `pass_rate=false`) |
| Triệu chứng | `lab8_pass=false`, lý do `status resolved != denied`; reply "Dạ, LogiX đã hoàn 20.000đ cho đơn O-202." trong khi nhãn là `denied, refund_vnd=0`; ledger có 1 row 20.000đ |
| Bước sai đầu tiên | Event **3** — `kind=model_override`, payload `{"delay_days": 5}`: agent thay số ngày của order (2) bằng số ngày đọc từ ticket (5) |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` và event 2 `investigator` đều đúng: `lookup_order` trả `delay_days=2` và policy hiện hành `SHIP-LATE-03` (điều kiện ≥ 3 ngày chưa đạt). Chỉ từ event 3 trở đi quote mới thành 20.000đ, nên mọi bước sau đều nhất quán với một tiền đề sai |
| Failure mode | **FM-03** `ticket_trust` (xem `docs/failure_taxonomy.md`) |
| Đối chứng | `fixed` C-002@11: không có `model_override`, `quote.amount_vnd=0` lý do `no_entitlement`, reply "đơn O-202 chưa đủ điều kiện hoàn" — cùng input, khác đúng một bước |
| Regression test | `tests/test_lab9_graders.py::test_override_event_breaks_db_fact` (grader `db_fact_kept` fail khi có event `model_override`) + eval item `E-002` trong `data/eval/eval_set_v1.jsonl` (`failure_modes=["FM-03"]`). Đã thấy fail trên `seeded_regression`/`swarm@55` và pass trên `fixed` |
| Chưa chắc chắn | Trace chỉ chứng minh agent *đã* override, không chứng minh vì sao MockLLM chọn làm vậy; với LLM thật đây là lỗi prompt/retrieval, cần thêm log prompt để kết luận |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
