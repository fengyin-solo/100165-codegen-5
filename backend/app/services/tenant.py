"""商业租户业务规则：合同维护、租金台账生成、账单逐行核销、铺位在租状态都收在这里。

与其它模块不同，合同与台账的变更会落盘（store.save_persisted），页面重开、
服务重启之后数据仍然在。铺位本身不单独维护，在租状态完全跟着租户合同走。
"""
from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.store import store

CONTRACT_MODULE = "tenant_contract"
LEDGER_MODULE = "tenant_ledger"

CONTRACT_REQUIRED = ["租户名称", "铺位号", "合同开始", "合同结束", "月租金", "保证金"]
LEDGER_REQUIRED = ["租户名称", "铺位号", "账期", "应收金额"]

CONTRACT_STATUSES = ["履行中", "已到期", "已终止"]
LEDGER_STATUSES = ["待核销", "已核销"]

# 账单文件必须包含的列；缺列时逐行提示并全部跳过，其余列可有可无。
BILL_COLUMNS = ["铺位号", "账期", "账单编号", "实收金额"]


def _money(value: Any) -> Decimal | None:
    """把页面或账单里的金额转成两位小数 Decimal；空值、负数、非数字一律视为非法。"""
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("￥", "").replace("¥", "")
    if not text:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    return amount.quantize(Decimal("0.01"))


def _parse_day(value: Any) -> date | None:
    text = str(value or "").strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _parse_period(value: Any) -> tuple[int, int] | None:
    """账期只认 YYYY-MM；2026-9 这种也放行，统一补零。"""
    text = str(value or "").strip()
    parts = text.split("-")
    if len(parts) != 2:
        return None
    try:
        year, month = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if month < 1 or month > 12:
        return None
    return year, month


def _period_label(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def _period_range(start: date, end: date) -> list[tuple[int, int]]:
    """合同覆盖到的整月账期：从起始月到结束月逐月生成，由调用方负责去重。"""
    periods: list[tuple[int, int]] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        periods.append((year, month))
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return periods


def _contract_status(contract: dict[str, Any], today: date | None = None) -> str:
    """合同状态按起止日期自动算；手工终止的合同保持已终止，不再被日期改回来。"""
    if contract.get("status") == "已终止":
        return "已终止"
    today = today or date.today()
    start = _parse_day(contract.get("合同开始"))
    end = _parse_day(contract.get("合同结束"))
    if start is None or end is None:
        return str(contract.get("status") or "履行中")
    if today < start:
        return "履行中"
    if today > end:
        return "已到期"
    return "履行中"


class TenantService:
    # ------------------------------------------------------------------ 合同
    def list_contracts(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(CONTRACT_MODULE)
        for row in rows:
            self._sync_contract(row)
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("租户名称", ""))
                or keyword in str(row.get("铺位号", ""))
                or keyword in str(row.get("合同编号", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start_index = max(page - 1, 0) * size
        return rows[start_index:start_index + size], total

    def get_contract(self, contract_id: int) -> dict[str, Any] | None:
        entry = store.find(CONTRACT_MODULE, contract_id)
        if entry is not None:
            self._sync_contract(entry)
        return entry

    def create_contract(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        cleaned: dict[str, Any] = {}
        for field in CONTRACT_REQUIRED:
            text = str(values.get(field) or "").strip()
            if not text:
                return None, f"缺少必填字段：{field}"
            cleaned[field] = text

        start = _parse_day(cleaned["合同开始"])
        end = _parse_day(cleaned["合同结束"])
        if start is None or end is None:
            return None, "合同起止日期格式应为 YYYY-MM-DD"
        if end < start:
            return None, "合同结束日期不能早于开始日期"

        rent = _money(cleaned["月租金"])
        deposit = _money(cleaned["保证金"])
        if rent is None or rent <= 0:
            return None, "月租金必须是大于 0 的数字"
        if deposit is None or deposit < 0:
            return None, "保证金必须是不小于 0 的数字"

        booth = cleaned["铺位号"]
        overlap = self._active_contract_of_booth(booth, exclude_id=None, today=start)
        if overlap is not None:
            return None, (
                f"铺位 {booth} 已被「{overlap.get('租户名称')}」的合同 "
                f"{overlap.get('合同编号')} 占用，起止日期不能重叠"
            )

        rows = store.rows(CONTRACT_MODULE)
        code = str(values.get("合同编号") or "").strip()
        if not code:
            code = f"HT-{date.today().year}-{len(rows) + 1:03d}"
        if any(str(row.get("合同编号")) == code for row in rows):
            return None, f"合同编号 {code} 已存在"

        entry: dict[str, Any] = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "合同编号": code,
            "租户名称": cleaned["租户名称"],
            "铺位号": booth,
            "合同开始": cleaned["合同开始"],
            "合同结束": cleaned["合同结束"],
            "月租金": float(rent),
            "保证金": float(deposit),
        }
        rows.append(entry)
        self._sync_contract(entry)
        store.save_persisted()
        return entry, None

    def terminate_contract(self, contract_id: int) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(CONTRACT_MODULE, contract_id)
        if entry is None:
            return None, f"合同 {contract_id} 不存在或已归档"
        self._sync_contract(entry)
        if entry["status"] == "已终止":
            return None, "该合同已经终止，无需重复操作"
        if entry["status"] == "已到期":
            return None, "合同已到期，不能再终止"
        entry["status"] = "已终止"
        entry["pending"] = False
        store.save_persisted()
        return entry, "合同已终止，铺位同步释放"

    def _sync_contract(self, contract: dict[str, Any]) -> None:
        """按起止日期刷新合同状态；铺位在租状态就是从这个状态派生的。"""
        new_status = _contract_status(contract)
        contract["status"] = new_status
        contract["pending"] = new_status == "履行中"
        contract.setdefault("abnormal", False)

    def _active_contract_of_booth(
        self,
        booth: str,
        *,
        exclude_id: int | None,
        today: date | None = None,
    ) -> dict[str, Any] | None:
        today = today or date.today()
        for row in store.rows(CONTRACT_MODULE):
            if exclude_id is not None and int(row.get("id", 0)) == exclude_id:
                continue
            if str(row.get("铺位号")) != booth:
                continue
            self._sync_contract(row)
            if row["status"] != "履行中":
                continue
            start = _parse_day(row.get("合同开始"))
            end = _parse_day(row.get("合同结束"))
            if start and end and start <= today <= end:
                return row
        return None

    # ------------------------------------------------------------------ 台账
    def _filtered_ledger(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        booth: str | None = None,
        period: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = store.rows(LEDGER_MODULE)
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("租户名称", ""))
                or keyword in str(row.get("铺位号", ""))
                or keyword in str(row.get("账单编号", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if booth:
            rows = [row for row in rows if str(row.get("铺位号")) == booth.strip()]
        if period:
            rows = [row for row in rows if str(row.get("账期")) == period.strip()]
        return rows

    def list_ledger(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        booth: str | None = None,
        period: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._filtered_ledger(keyword=keyword, status=status, booth=booth, period=period)
        rows.sort(key=lambda row: (str(row.get("账期", "")), str(row.get("铺位号", ""))))
        total = len(rows)
        start_index = max(page - 1, 0) * size
        return rows[start_index:start_index + size], total

    def ledger_summary(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        booth: str | None = None,
        period: str | None = None,
    ) -> dict[str, float | int]:
        """台账合计：页面卡片与导出清单共用本口径，保证数字一致。"""
        rows = self._filtered_ledger(keyword=keyword, status=status, booth=booth, period=period)
        due_total = Decimal("0")
        paid_total = Decimal("0")
        for row in rows:
            due = _money(row.get("应收金额")) or Decimal("0")
            due_total += due
            if row.get("status") == "已核销":
                paid = _money(row.get("实收金额"))
                paid_total += paid if paid is not None else due
        due_total = due_total.quantize(Decimal("0.01"))
        paid_total = paid_total.quantize(Decimal("0.01"))
        return {
            "count": len(rows),
            "due_total": float(due_total),
            "paid_total": float(paid_total),
            "unpaid_total": float(due_total - paid_total),
        }

    def generate_ledger(self, contract_id: int | None = None) -> tuple[dict[str, int] | None, str | None]:
        """按合同逐月生成租金台账；已经存在的账期跳过，保证同一账期不重复入账。"""
        contracts = store.rows(CONTRACT_MODULE)
        targets = [store.find(CONTRACT_MODULE, contract_id)] if contract_id else contracts
        if contract_id and targets[0] is None:
            return None, f"合同 {contract_id} 不存在或已归档"

        created = 0
        skipped = 0
        ledger_rows = store.rows(LEDGER_MODULE)

        def next_id() -> int:
            return max((int(row.get("id", 0)) for row in ledger_rows), default=0) + 1

        for contract in targets:
            if contract is None:
                continue
            self._sync_contract(contract)
            if contract["status"] == "已终止":
                # 终止的合同不再补账期；已生成的历史台账保持不变。
                continue
            start = _parse_day(contract.get("合同开始"))
            end = _parse_day(contract.get("合同结束"))
            rent = _money(contract.get("月租金"))
            if start is None or end is None or rent is None:
                continue
            for year, month in _period_range(start, end):
                label = _period_label(year, month)
                exists = any(
                    str(row.get("铺位号")) == str(contract["铺位号"])
                    and str(row.get("账期")) == label
                    for row in ledger_rows
                )
                if exists:
                    skipped += 1
                    continue
                ledger_rows.append({
                    "id": next_id(),
                    "status": "待核销",
                    "pending": True,
                    "abnormal": False,
                    "合同编号": contract["合同编号"],
                    "租户名称": contract["租户名称"],
                    "铺位号": contract["铺位号"],
                    "账期": label,
                    "应收金额": float(rent),
                    "实收金额": None,
                    "账单编号": None,
                    "核销日期": None,
                })
                created += 1
        store.save_persisted()
        return {"created": created, "skipped": skipped}, None

    # -------------------------------------------------------------- 账单核销
    def import_bills(self, file_name: str, content: str) -> dict[str, Any]:
        """解析一批账单并逐行核销。

        任何一行出错（缺列、金额与月租对不上、同一账期重复等）都只跳过那一行，
        剩下合法的行继续入账；结果里逐行给出原因。
        """
        reader = csv.DictReader(io.StringIO(content))
        headers = reader.fieldnames or []
        headers = [str(name or "").strip() for name in headers]

        results: list[dict[str, Any]] = []
        missing_columns = [col for col in BILL_COLUMNS if col not in headers]
        imported = 0

        if missing_columns:
            # 表头缺列：数据行无法可靠定位列，逐行记录跳过原因。
            for index, raw in enumerate(reader, start=2):
                results.append({
                    "line": index,
                    "ok": False,
                    "message": f"文件缺少必需列：{'、'.join(missing_columns)}，整行跳过",
                    "raw": dict(raw),
                })
        else:
            ledger_rows = store.rows(LEDGER_MODULE)
            seen_bills: set[str] = set()

            for index, raw in enumerate(reader, start=2):
                raw = {str(key or "").strip(): (value or "").strip() for key, value in raw.items()}
                if not any(raw.values()):
                    # 完全空行不计入账，也不算错误，免得把文件尾部空行当异常。
                    continue
                row_ref, message = self._match_ledger_row(raw, ledger_rows, seen_bills)
                if row_ref is None:
                    results.append({"line": index, "ok": False, "message": message, "raw": raw})
                    continue
                paid = _money(raw.get("实收金额"))
                bill_no = raw["账单编号"]
                row_ref["实收金额"] = float(paid)
                row_ref["账单编号"] = bill_no
                row_ref["核销日期"] = date.today().isoformat()
                row_ref["status"] = "已核销"
                row_ref["pending"] = False
                seen_bills.add(bill_no)
                imported += 1
                results.append({
                    "line": index,
                    "ok": True,
                    "message": (
                        f"核销成功：{row_ref['铺位号']} {row_ref['账期']} "
                        f"实收 {paid}，账单 {bill_no}"
                    ),
                    "raw": raw,
                })
            if imported:
                store.save_persisted()

        return {
            "file_name": file_name,
            "total": len(results),
            "imported": imported,
            "skipped": len(results) - imported,
            "missing_columns": missing_columns,
            "results": results,
        }

    def _match_ledger_row(
        self,
        raw: dict[str, str],
        ledger_rows: list[dict[str, Any]],
        seen_bills: set[str],
    ) -> tuple[dict[str, Any] | None, str]:
        for col in BILL_COLUMNS:
            if not raw.get(col):
                return None, f"缺少必填内容：{col}，本行跳过"

        booth = raw["铺位号"]
        label_raw = raw["账期"]
        bill_no = raw["账单编号"]
        paid = _money(raw.get("实收金额"))
        if paid is None or paid < 0:
            return None, f"实收金额「{raw.get('实收金额')}」不是合法金额，本行跳过"

        period = _parse_period(label_raw)
        if period is None:
            return None, f"账期「{label_raw}」格式应为 YYYY-MM，本行跳过"
        label = _period_label(*period)

        if bill_no in seen_bills:
            return None, f"账单编号 {bill_no} 在本批文件中重复，本行跳过"
        if any(str(row.get("账单编号")) == bill_no for row in ledger_rows):
            return None, f"账单编号 {bill_no} 已核销过，重复送账，本行跳过"

        matches = [
            row for row in ledger_rows
            if str(row.get("铺位号")) == booth and str(row.get("账期")) == label
        ]
        if not matches:
            return None, f"铺位 {booth} 在 {label} 没有对应租金台账，请先生成台账，本行跳过"
        row = matches[0]
        if row.get("status") == "已核销":
            existing = row.get("账单编号") or "历史账单"
            return None, f"铺位 {booth} {label} 已由账单 {existing} 核销，同一账期重复，本行跳过"

        rent = _money(row.get("应收金额"))
        if rent is None or paid != rent:
            return None, (
                f"实收金额 {paid} 与合同月租金 {rent or '—'} 不一致，本行跳过"
            )
        return row, ""

    # ------------------------------------------------------------------ 铺位
    def list_booths(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """铺位清单直接由合同推导：同一铺位以最新一份合同决定在租状态。"""
        booths: dict[str, dict[str, Any]] = {}
        for contract in store.rows(CONTRACT_MODULE):
            self._sync_contract(contract)
            booth = str(contract["铺位号"])
            current = booths.get(booth)
            if current is None or str(contract.get("合同开始", "")) > str(current.get("合同开始", "")):
                active = contract["status"] == "履行中"
                booths[booth] = {
                    "铺位号": booth,
                    "在租状态": "在租" if active else "空闲",
                    "租户名称": contract["租户名称"] if active else "",
                    "合同编号": contract["合同编号"] if active else contract["合同编号"],
                    "合同开始": contract["合同开始"],
                    "合同结束": contract["合同结束"],
                    "月租金": contract["月租金"],
                }
        rows = list(booths.values())
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row["铺位号"]) or keyword in str(row["租户名称"])
            ]
        if status:
            rows = [row for row in rows if row["在租状态"] == status]
        rows.sort(key=lambda row: str(row["铺位号"]))
        return rows
