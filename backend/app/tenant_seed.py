"""商业租户模块的初始数据：首次启动没有 JSON 文件时落一份可演示的合同与台账。"""
from __future__ import annotations

from typing import Any


def _build_ledgers(
    contract: dict[str, Any], periods: list[str], paid_periods: set[str]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rent = float(contract["月租金"])
    for index, period in enumerate(periods, start=1):
        written_off = period in paid_periods
        rows.append({
            "id": 0,  # 由 build_initial_data 统一编号
            "合同编号": contract["合同编号"],
            "租户名称": contract["租户名称"],
            "铺位号": contract["铺位号"],
            "账期": period,
            "应收金额": rent,
            "实收金额": rent if written_off else 0.0,
            "核销状态": "已核销" if written_off else "待核销",
            "账单编号": f"BILL-{contract['合同编号']}-{index:02d}" if written_off else "",
            "核销日期": "2026-08-05" if written_off else "",
        })
    return rows


def _periods(start: str, end: str) -> list[str]:
    start_year, start_month = (int(part) for part in start.split("-")[:2])
    end_year, end_month = (int(part) for part in end.split("-")[:2])
    periods: list[str] = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        periods.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1
    return periods


def build_initial_data() -> dict[str, Any]:
    contracts = [
        {
            "id": 1,
            "合同编号": "TZ-HT-0001",
            "租户名称": "云岚咖啡",
            "铺位号": "B1-101",
            "合同开始": "2026-01-01",
            "合同截止": "2026-12-31",
            "月租金": 12000.0,
            "保证金": 24000.0,
        },
        {
            "id": 2,
            "合同编号": "TZ-HT-0002",
            "租户名称": "悦读书店",
            "铺位号": "B1-108",
            "合同开始": "2026-03-01",
            "合同截止": "2027-02-28",
            "月租金": 8600.0,
            "保证金": 17200.0,
        },
        {
            "id": 3,
            "合同编号": "TZ-HT-0003",
            "租户名称": "晴川便利",
            "铺位号": "B2-205",
            "合同开始": "2025-09-01",
            "合同截止": "2026-06-30",
            "月租金": 9800.0,
            "保证金": 19600.0,
        },
    ]

    ledger_rows: list[dict[str, Any]] = []
    # 云岚咖啡 1~8 月账单已核销，9~12 月仍待收；其余合同全部待核销，方便演示导入。
    paid = {f"2026-{month:02d}" for month in range(1, 9)}
    for contract in contracts:
        periods = _periods(contract["合同开始"], contract["合同截止"])
        ledger_rows.extend(_build_ledgers(contract, periods, paid))
    for index, row in enumerate(ledger_rows, start=1):
        row["id"] = index

    return {"contracts": contracts, "ledgers": ledger_rows}
