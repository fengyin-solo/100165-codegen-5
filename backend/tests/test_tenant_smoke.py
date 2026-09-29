"""商业租户模块端到端冒烟测试：不依赖第三方测试框架，标准库 + FastAPI TestClient 即可跑。

用法：TENANT_DATA_FILE=$(mktemp) .venv/bin/python -m tests.test_tenant_smoke
（不设 TENANT_DATA_FILE 时也会自动用临时文件，避免污染日常演示数据。）
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

# 必须在导入应用代码前指定数据文件，让测试数据与日常演示数据隔离。
if "TENANT_DATA_FILE" not in os.environ:
    _fd, _name = tempfile.mkstemp(prefix="tenant-test-", suffix=".json")
    os.close(_fd)
    os.environ["TENANT_DATA_FILE"] = _name

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {name}" + (f" -> {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(f"{name}: {detail}")


def main() -> int:
    # 1. 合同列表带在租状态，初始 3 份合同，铺位状态来自合同日期。
    resp = client.get("/api/tenant/contracts")
    contracts = resp.json()["items"]
    check("合同列表初始 3 份", len(contracts) == 3, str(len(contracts)))
    by_booth = {row["铺位号"]: row for row in contracts}
    check("在租合同状态为在租", by_booth["B1-101"]["在租状态"] == "在租", by_booth["B1-101"]["在租状态"])
    check("过期合同状态为已到期", by_booth["B2-205"]["在租状态"] == "已到期", by_booth["B2-205"]["在租状态"])

    # 2. 登记新合同后自动按月生成台账。
    payload = {
        "values": {
            "租户名称": "测试花坊",
            "铺位号": "T-9001",
            "合同开始": "2026-07-01",
            "合同截止": "2026-09-30",
            "月租金": "3,000.00",
            "保证金": 6000,
        }
    }
    resp = client.post("/api/tenant/contracts", json=payload)
    body = resp.json()
    check("登记合同成功", body["ok"] is True, body.get("message", ""))
    contract_id = body["entry"]["id"]
    check("新铺位状态为在租", body["entry"]["在租状态"] == "在租", body["entry"]["在租状态"])

    resp = client.get("/api/tenant/ledgers", params={"booth": "T-9001"})
    data = resp.json()
    periods = [row["账期"] for row in data["items"]]
    check("按合同生成 3 期台账", periods == ["2026-07", "2026-08", "2026-09"], str(periods))
    check("台账初始待核销", all(row["核销状态"] == "待核销" for row in data["items"]))
    check("页面合计等于明细求和", abs(data["summary"]["应收合计"] - 9000.0) < 0.01, str(data["summary"]))

    # 3. 导入账单：好行入账，坏行逐行跳过，其余继续。
    csv_text = (
        "铺位号,账期,账单编号,金额\n"
        "T-9001,2026-07,BILL-T-07,3000\n"        # 正常
        "T-9001,2026-08,BILL-T-08,2999\n"        # 金额与月租对不上
        "T-9001,,BILL-T-09,3000\n"               # 账期缺列
        "T-9001,2026-07,BILL-T-07B,3000\n"       # 同账期重复（台账已核销）
        "NO-SUCH,2026-07,BILL-X,3000\n"          # 铺位无合同
    )
    resp = client.post("/api/tenant/ledgers/import-text", json={"content": csv_text})
    result = resp.json()
    check("导入返回总行数 5", result["总行数"] == 5, str(result["总行数"]))
    check("仅 1 行入账", result["成功行数"] == 1, str(result["成功行数"]))
    check("4 行被跳过", result["跳过行数"] == 4, str(result["跳过行数"]))
    reasons = {row["行号"]: row["原因"] for row in result["明细"] if not row["ok"]}
    check("金额不符逐行提示", "金额" in reasons[2] and "不一致" in reasons[2], reasons.get(2, ""))
    check("缺列逐行提示", "缺列" in reasons[3], reasons.get(3, ""))
    check("同账期重复逐行提示", "重复" in reasons[4] or "已核销" in reasons[4], reasons.get(4, ""))
    check("无合同铺位逐行提示", "没有在租合同" in reasons[5], reasons.get(5, ""))

    # 跳过行没有影响其它账期：7 月已核销，8、9 月仍待核销。
    resp = client.get("/api/tenant/ledgers", params={"booth": "T-9001"})
    rows = {row["账期"]: row for row in resp.json()["items"]}
    check("好行已核销", rows["2026-07"]["核销状态"] == "已核销" and rows["2026-07"]["账单编号"] == "BILL-T-07")
    check("金额不符行未入账", rows["2026-08"]["核销状态"] == "待核销")
    check("缺列行未入账", rows["2026-09"]["核销状态"] == "待核销")
    check("核销后实收=应收", float(rows["2026-07"]["实收金额"]) == 3000.0)

    # 同一文件内重复同样只跳过该行。
    dup_in_file = (
        "铺位号,账期,账单编号,金额\n"
        "T-9001,2026-08,BILL-A,3000\n"
        "T-9001,2026-08,BILL-B,3000\n"
    )
    result = client.post("/api/tenant/ledgers/import-text", json={"content": dup_in_file}).json()
    check("文件内重复只跳过第二行", result["成功行数"] == 1 and result["跳过行数"] == 1, str(result))

    # 4. 表头缺列整文件拒绝，且不改动任何数据。
    resp = client.post(
        "/api/tenant/ledgers/import-text",
        json={"content": "铺位号,账期,金额\nT-9001,2026-09,3000\n"},
    )
    check("缺列表头返回 400", resp.status_code == 400 and "账单编号" in resp.json()["detail"], str(resp.status_code))

    # 5. 清单合计与页面数字一致（同一筛选口径，JSON 与 CSV 同源）。
    resp_json = client.get("/api/tenant/ledgers/export-json", params={"booth": "T-9001"}).json()
    resp_csv = client.get("/api/tenant/ledgers/export", params={"booth": "T-9001"}).text
    resp_page = client.get("/api/tenant/ledgers", params={"booth": "T-9001"}).json()
    check("清单与页面 summary 同源", resp_json["summary"] == resp_page["summary"])
    check("CSV 末行合计与页面一致", f"{resp_page['summary']['应收合计']}" in resp_csv and "合计" in resp_csv)
    sums = resp_page["summary"]
    check(
        "合计勾稽：应收=已核销+待核销",
        abs(sums["应收合计"] - sums["已核销合计"] - sums["待核销合计"]) < 0.01,
        str(sums),
    )

    # 6. 铺位状态跟随合同：终止后立即变化。
    resp = client.post(f"/api/tenant/contracts/{contract_id}/actions", json={"action": "终止合同"})
    check("终止合同成功", resp.json()["ok"] is True, resp.json().get("message", ""))
    booth = client.get("/api/tenant/booths", params={"booth": "T-9001"}).json()["items"][0]
    check("铺位状态随合同变已终止", booth["在租状态"] == "已终止", booth["在租状态"])

    # 6.5 已到期合同的铺位可以重新招租，且账单优先核销到新合同。
    resp = client.post(
        "/api/tenant/contracts",
        json={
            "values": {
                "租户名称": "新晴川便利",
                "铺位号": "B2-205",
                "合同开始": "2026-10-01",
                "合同截止": "2027-09-30",
                "月租金": 10000,
                "保证金": 20000,
            }
        },
    )
    check("到期铺位允许重新签合同", resp.json()["ok"] is True, resp.json().get("message", ""))
    new_contract_no = resp.json()["entry"]["合同编号"]
    resp = client.post(
        "/api/tenant/ledgers/import-text",
        json={"content": "铺位号,账期,账单编号,金额\nB2-205,2026-10,BILL-NEW-10,10000\n"},
    )
    result = resp.json()
    check("新合同账期核销成功", result["成功行数"] == 1, str(result))
    ledgers = client.get(
        "/api/tenant/ledgers", params={"booth": "B2-205", "period": "2026-10"}
    ).json()["items"]
    paid_rows = [row for row in ledgers if row["核销状态"] == "已核销"]
    check("账单核销到新合同而非历史合同", len(paid_rows) == 1 and paid_rows[0]["合同编号"] == new_contract_no, str(paid_rows))

    # 7. 其它模块查询方式照旧、概览不受影响。
    resp = client.get("/api/health")
    check("健康检查模块数仍为 18", resp.json()["modules"] == 18, str(resp.json()["modules"]))
    resp = client.get("/api/settlement")
    check("保障结算分页结构照旧", set(["items", "total", "page", "size"]).issubset(resp.json().keys()))
    resp = client.get("/api/flight?page=1&size=5")
    check("航班计划查询照旧", resp.status_code == 200 and "items" in resp.json())

    # 8. 持久化：落盘文件存在且重启后数据仍在（直接新起一个 Store 实例模拟）。
    data_file = Path(os.environ["TENANT_DATA_FILE"])
    check("数据已落盘", data_file.exists() and data_file.stat().st_size > 0)
    import app.tenant_store as tenant_store_module

    fresh_store = tenant_store_module.TenantStore(data_file)
    fresh_booths = {
        row["铺位号"]: row
        for row in fresh_store.contracts
    }
    check("重开后新合同仍在", "T-9001" in fresh_booths and fresh_booths["T-9001"].get("已终止") is True)
    fresh_paid = [
        row for row in fresh_store.ledgers
        if row["铺位号"] == "T-9001" and row["核销状态"] == "已核销"
    ]
    check("重开后核销记录仍在", len(fresh_paid) == 2 and fresh_paid[0]["账单编号"] == "BILL-T-07", str(len(fresh_paid)))

    print()
    if failures:
        print(f"{len(failures)} 项未通过：")
        for item in failures:
            print(" -", item)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
