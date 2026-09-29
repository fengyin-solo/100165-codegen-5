"""商业租户业务规则：合同维护、按合同生成租金台账、账单导入逐行核销。

校验口径集中在这里，路由层只负责收发：
- 合同起止按月生成台账，同合同同账期只生成一次；
- 导入账单按行校验（缺列、金额与月租不一致、同账期重复），坏行只跳过自身并逐行回原因，
  好行继续核销入账；
- 铺位在租状态完全由合同（起止日期 + 是否终止）推导，合同落盘后状态即持久。
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date
from typing import Any

from app.tenant_store import tenant_store

REQUIRED_CONTRACT_FIELDS = ["租户名称", "铺位号", "合同开始", "合同截止", "月租金", "保证金"]
LEDGER_FIELDS = ["合同编号", "租户名称", "铺位号", "账期", "应收金额", "实收金额", "核销状态", "账单编号", "核销日期"]

# 账单文件必须具备的列；表头别名兼容不同来源的模板。
BILL_COLUMNS = ["铺位号", "账期", "账单编号", "金额"]
COLUMN_ALIASES = {
    "铺位号": {"铺位号", "铺位", "店铺号", "铺位编号"},
    "账期": {"账期", "账单月份", "费用月份", "所属月份", "账期(年-月)"},
    "账单编号": {"账单编号", "账单号", "单据编号", "单号"},
    "金额": {"金额", "账单金额", "实收金额", "核销金额", "到账金额"},
}


def parse_period(value: Any) -> str | None:
    """把 '2026-9'、'2026/09'、'2026年09月' 等写法统一成 'YYYY-MM'。"""
    text = str(value or "").strip()
    # 兼容 2026-09 / 2026/9 / 2026年09月 / 2026-10-01 等写法，统一取年、月。
    match = re.match(r"^\s*(\d{4})\D{0,2}(\d{1,2})(?:\D.*)?$", text)
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return None
    return f"{year:04d}-{month:02d}"


def parse_money(value: Any) -> float | None:
    """解析金额，去掉千分位逗号、货币符号与空格；非法返回 None。"""
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("，", "")
    text = text.replace("￥", "").replace("¥", "").replace("元", "").strip()
    if not text:
        return None
    try:
        amount = float(text)
    except ValueError:
        return None
    return round(amount, 2) if amount >= 0 else None


def parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def contract_status(contract: dict[str, Any], today: date | None = None) -> str:
    """铺位在租状态跟着合同走：已终止 / 未到期 / 在租 / 已到期。"""
    today = today or date.today()
    if contract.get("已终止"):
        return "已终止"
    start = parse_date(contract.get("合同开始"))
    end = parse_date(contract.get("合同截止"))
    if start is None or end is None:
        return "未到期"
    if today < start:
        return "未到期"
    if end < today:
        return "已到期"
    return "在租"


def iter_periods(start: str, end: str) -> list[str]:
    start_date = parse_date(start)
    end_date = parse_date(end)
    if start_date is None or end_date is None or end_date < start_date:
        return []
    periods: list[str] = []
    year, month = start_date.year, start_date.month
    while (year, month) <= (end_date.year, end_date.month):
        periods.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1
    return periods


class TenantService:
    # ---------------- 合同 ----------------
    def list_contracts(self, *, keyword: str | None = None) -> list[dict[str, Any]]:
        rows = [self._decorate_contract(row) for row in tenant_store.contracts]
        if keyword:
            keyword = keyword.strip()
            rows = [
                row for row in rows
                if keyword in str(row["租户名称"])
                or keyword in str(row["铺位号"])
                or keyword in str(row["合同编号"])
            ]
        rows.sort(key=lambda row: int(row["id"]), reverse=True)
        return rows

    def get_contract(self, contract_id: int) -> dict[str, Any] | None:
        row = tenant_store.find_contract(contract_id)
        return self._decorate_contract(row) if row else None

    def _decorate_contract(self, row: dict[str, Any]) -> dict[str, Any]:
        entry = dict(row)
        entry["在租状态"] = contract_status(row)
        return entry

    def create_contract(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        cleaned, missing = self._clean_contract(values)
        if missing:
            return None, missing
        next_id = tenant_store.next_contract_id()
        contract: dict[str, Any] = {
            "id": next_id,
            "合同编号": f"TZ-HT-{next_id:04d}",
            "已终止": False,
        }
        contract.update(cleaned)
        # 合同与首期台账一起落盘，避免台账生成失败时留下一份半拉合同。
        tenant_store.contracts.append(contract)
        self.generate_ledgers(next_id, persist=False)
        tenant_store.save()
        return self._decorate_contract(contract), []

    def update_contract(self, contract_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        contract = tenant_store.find_contract(contract_id)
        if contract is None:
            return None, f"合同 {contract_id} 不存在"
        cleaned, missing = self._clean_contract(values, ignore_id=contract_id)
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        contract.update(cleaned)
        tenant_store.save()
        # 起止或租金变化后补齐新账期，旧的核销记录保留。
        self.generate_ledgers(contract_id)
        return self._decorate_contract(contract), "合同已更新，租金台账已同步"

    def terminate_contract(self, contract_id: int) -> tuple[dict[str, Any] | None, str]:
        contract = tenant_store.find_contract(contract_id)
        if contract is None:
            return None, f"合同 {contract_id} 不存在"
        contract["已终止"] = True
        tenant_store.save()
        return self._decorate_contract(contract), "合同已终止，铺位状态同步为已终止"

    def _clean_contract(
        self, values: dict[str, Any], *, ignore_id: int | None = None
    ) -> tuple[dict[str, Any], list[str]]:
        missing = [
            field for field in REQUIRED_CONTRACT_FIELDS
            if str(values.get(field) or "").strip() == ""
        ]
        rent = parse_money(values.get("月租金"))
        deposit = parse_money(values.get("保证金"))
        start = str(values.get("合同开始") or "").strip()
        end = str(values.get("合同截止") or "").strip()
        if values.get("月租金") not in (None, "") and rent is None:
            missing.append("月租金(须为数字)")
        if values.get("保证金") not in (None, "") and deposit is None:
            missing.append("保证金(须为数字)")
        if start and parse_date(start) is None:
            missing.append("合同开始(格式 YYYY-MM-DD)")
        if end and parse_date(end) is None:
            missing.append("合同截止(格式 YYYY-MM-DD)")
        if start and end and parse_date(start) and parse_date(end) and parse_date(end) < parse_date(start):
            missing.append("合同截止(不得早于开始日期)")
        if missing:
            return {}, missing

        booth = str(values["铺位号"]).strip()
        # 合同已终止或已自然到期的铺位允许重新招租，只挡仍在租期内/未起租的。
        duplicate = next(
            (
                row for row in tenant_store.contracts
                if str(row.get("铺位号", "")).strip() == booth
                and (ignore_id is None or int(row.get("id", 0)) != ignore_id)
                and contract_status(row) in {"在租", "未到期"}
            ),
            None,
        )
        if duplicate is not None:
            return {}, [f"铺位 {booth} 已有在租合同（{duplicate['合同编号']}）"]

        cleaned = {
            "租户名称": str(values["租户名称"]).strip(),
            "铺位号": booth,
            "合同开始": start,
            "合同截止": end,
            "月租金": rent,
            "保证金": deposit,
        }
        return cleaned, []

    # ---------------- 租金台账 ----------------
    def generate_ledgers(self, contract_id: int, *, persist: bool = True) -> tuple[list[dict[str, Any]], str]:
        """按合同起止逐月铺台账；同合同同账期已存在的行不动（核销结果保留）。"""
        contract = tenant_store.find_contract(contract_id)
        if contract is None:
            return [], f"合同 {contract_id} 不存在"
        existing = {
            (row["合同编号"], row["账期"]): row
            for row in tenant_store.ledgers
        }
        created: list[dict[str, Any]] = []
        for period in iter_periods(contract["合同开始"], contract["合同截止"]):
            key = (contract["合同编号"], period)
            if key in existing:
                row = existing[key]
            else:
                row = {
                    "id": tenant_store.next_ledger_id(),
                    "合同编号": contract["合同编号"],
                    "租户名称": contract["租户名称"],
                    "铺位号": contract["铺位号"],
                    "账期": period,
                    "应收金额": round(float(contract["月租金"]), 2),
                    "实收金额": 0.0,
                    "核销状态": "待核销",
                    "账单编号": "",
                    "核销日期": "",
                }
                tenant_store.ledgers.append(row)
                created.append(row)
                continue
            # 合同金额/主体可能被编辑过，未核销的行跟着合同口径刷新。
            if row["核销状态"] == "待核销":
                row["租户名称"] = contract["租户名称"]
                row["铺位号"] = contract["铺位号"]
                row["应收金额"] = round(float(contract["月租金"]), 2)
        if persist:
            tenant_store.save()
        if created:
            message = f"合同 {contract['合同编号']} 新增 {len(created)} 期租金台账"
        else:
            message = f"合同 {contract['合同编号']} 台账已是最新，无新增账期"
        return created, message

    def list_ledgers(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        period: str | None = None,
        booth: str | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        rows = [dict(row) for row in tenant_store.ledgers]
        if keyword:
            keyword = keyword.strip()
            rows = [
                row for row in rows
                if keyword in str(row["租户名称"])
                or keyword in str(row["合同编号"])
                or keyword in str(row["铺位号"])
            ]
        if booth:
            booth = booth.strip()
            rows = [row for row in rows if booth in str(row["铺位号"])]
        if status:
            rows = [row for row in rows if row["核销状态"] == status]
        if period:
            normalized = parse_period(period)
            if normalized:
                rows = [row for row in rows if row["账期"] == normalized]
        rows.sort(key=lambda row: (str(row["账期"]), str(row["铺位号"])))
        summary = self.summarize(rows)
        return rows, summary

    def summarize(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        receivable = round(sum(float(row["应收金额"]) for row in rows), 2)
        received = round(sum(float(row["实收金额"]) for row in rows), 2)
        return {
            "总期数": len(rows),
            "已核销期数": sum(1 for row in rows if row["核销状态"] == "已核销"),
            "待核销期数": sum(1 for row in rows if row["核销状态"] == "待核销"),
            "应收合计": receivable,
            "已核销合计": received,
            "待核销合计": round(receivable - received, 2),
        }

    # ---------------- 账单导入核销 ----------------
    def parse_bill_file(self, raw: bytes | str, filename: str = "") -> tuple[list[dict[str, str]], list[str]]:
        """解析 CSV；表头缺列时整文件不核销，并把缺的列名列清楚。"""
        if isinstance(raw, bytes):
            text = None
            for encoding in ("utf-8-sig", "utf-8", "gbk"):
                try:
                    text = raw.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            if text is None:
                return [], ["文件无法识别为 UTF-8/GBK 文本，请另存为 CSV 后再导入"]
        else:
            text = raw
        if filename.lower().endswith(".xlsx") or filename.lower().endswith(".xls"):
            return [], ["暂不支持 Excel 文件，请另存为 CSV（UTF-8）后再导入"]
        try:
            reader = csv.DictReader(io.StringIO(text))
        except csv.Error as exc:
            return [], [f"CSV 解析失败：{exc}"]
        headers = reader.fieldnames or []
        header_map = self._map_columns(headers)
        missing = [column for column in BILL_COLUMNS if column not in header_map]
        if missing:
            return [], [f"导入文件缺少必填列：{'、'.join(missing)}（应有列：{'、'.join(BILL_COLUMNS)}）"]
        records: list[dict[str, str]] = []
        for raw_row in reader:
            records.append({column: (raw_row.get(actual) or "").strip() for column, actual in header_map.items()})
        return records, []

    def _map_columns(self, headers: list[str]) -> dict[str, str]:
        normalized = {str(name).strip(): str(name).strip() for name in headers if name}
        result: dict[str, str] = {}
        for column, aliases in COLUMN_ALIASES.items():
            for header, original in normalized.items():
                if header in aliases:
                    result[column] = original
                    break
        return result

    def import_bills(self, records: list[dict[str, str]], today: date | None = None) -> dict[str, Any]:
        """逐行核销账单：坏行只跳过自己并回原因，好行继续入账；同批内重复也算重复。"""
        today = today or date.today()
        results: list[dict[str, Any]] = []
        imported: list[dict[str, Any]] = []
        seen_in_batch: set[tuple[str, str]] = set()

        # 同一铺位可能留有历史合同，导入时优先认在租/未到期的合同；没有再退回历史合同。
        active_statuses = {"在租", "未到期"}
        contracts_by_booth: dict[str, dict[str, Any]] = {}
        for row in tenant_store.contracts:
            booth_key = str(row["铺位号"]).strip()
            current = contracts_by_booth.get(booth_key)
            if current is None or (
                contract_status(current) not in active_statuses
                and contract_status(row) in active_statuses
            ):
                contracts_by_booth[booth_key] = row

        for index, record in enumerate(records, start=1):
            booth = record.get("铺位号", "").strip()
            period_text = record.get("账期", "").strip()
            bill_no = record.get("账单编号", "").strip()
            amount_text = record.get("金额", "").strip()

            problems: list[str] = []
            if not booth:
                problems.append("缺列：铺位号为空")
            if not period_text:
                problems.append("缺列：账期为空")
            if not bill_no:
                problems.append("缺列：账单编号为空")
            if not amount_text:
                problems.append("缺列：金额为空")

            period = parse_period(period_text) if period_text else None
            if period_text and period is None:
                problems.append(f"账期「{period_text}」格式无法识别（应为 YYYY-MM）")
            amount = parse_money(amount_text) if amount_text else None
            if amount_text and amount is None:
                problems.append(f"金额「{amount_text}」无法识别为数字")

            contract = contracts_by_booth.get(booth) if booth else None
            if booth and contract is None:
                problems.append(f"铺位 {booth} 没有在租合同，无法核销")

            if contract is not None and period is not None:
                periods = iter_periods(contract["合同开始"], contract["合同截止"])
                if period not in periods:
                    problems.append(
                        f"账期 {period} 不在合同 {contract['合同编号']} 期内"
                        f"（{contract['合同开始']} ~ {contract['合同截止']}）"
                    )
                if amount is not None and abs(amount - float(contract["月租金"])) > 0.01:
                    problems.append(
                        f"金额 {amount:.2f} 与月租金 {float(contract['月租金']):.2f} 不一致"
                    )

            dedup_key = (booth, period or "")
            ledger: dict[str, Any] | None = None
            if contract is not None and period is not None and not problems:
                ledger = next(
                    (
                        row for row in tenant_store.ledgers
                        if row["合同编号"] == contract["合同编号"] and row["账期"] == period
                    ),
                    None,
                )
                if ledger is None:
                    problems.append(f"合同 {contract['合同编号']} 在 {period} 没有对应租金台账")
                elif ledger["核销状态"] == "已核销":
                    problems.append(
                        f"账期 {period} 已核销（账单编号 {ledger['账单编号']}），请勿重复送单"
                    )
                elif dedup_key in seen_in_batch:
                    problems.append(f"账期 {period} 在本文件内重复出现")

            if problems:
                results.append({
                    "行号": index,
                    "ok": False,
                    "铺位号": booth,
                    "账期": period or period_text,
                    "账单编号": bill_no,
                    "金额": amount_text,
                    "原因": "；".join(problems),
                })
                # 重复行也要占住批次去重键，保证同批第二条一样被拦下。
                if booth and period:
                    seen_in_batch.add(dedup_key)
                continue

            assert ledger is not None and contract is not None
            assert amount is not None
            ledger["实收金额"] = round(float(amount), 2)
            ledger["核销状态"] = "已核销"
            ledger["账单编号"] = bill_no
            ledger["核销日期"] = today.isoformat()
            seen_in_batch.add(dedup_key)
            imported.append(ledger)
            results.append({
                "行号": index,
                "ok": True,
                "铺位号": booth,
                "账期": period,
                "账单编号": bill_no,
                "金额": round(float(amount), 2),
                "原因": "核销成功",
            })

        if imported:
            tenant_store.save()

        imported_amount = round(sum(float(row["实收金额"]) for row in imported), 2)
        return {
            "总行数": len(records),
            "成功行数": len(imported),
            "跳过行数": len(records) - len(imported),
            "核销金额": imported_amount,
            "明细": results,
        }

    # ---------------- 铺位状态 ----------------
    def list_booths(self, *, booth: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        """铺位视图：同一铺位只展示一份在租合同，状态完全跟随合同。"""
        result: list[dict[str, Any]] = []
        for contract in tenant_store.contracts:
            current = contract_status(contract)
            if status and current != status:
                continue
            if booth and booth.strip() not in str(contract["铺位号"]):
                continue
            result.append({
                "铺位号": contract["铺位号"],
                "在租状态": current,
                "租户名称": contract["租户名称"],
                "合同编号": contract["合同编号"],
                "合同开始": contract["合同开始"],
                "合同截止": contract["合同截止"],
                "月租金": contract["月租金"],
                "保证金": contract["保证金"],
            })
        result.sort(key=lambda row: str(row["铺位号"]))
        return result
