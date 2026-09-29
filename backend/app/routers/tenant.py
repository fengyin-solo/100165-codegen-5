"""商业租户接口：租户合同、租金台账、账单核销与铺位在租状态。

查询方式（GET 列表 + 关键字/状态过滤 + 分页、导出清单）与其它模块保持一致；
账单导入只接受 CSV 文本（前端读取文件内容后提交），逐行返回核销结果。
"""
from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.schemas import (
    ActionResult,
    BillImportResult,
    EntryPayload,
    LedgerSummary,
    PageResult,
)
from app.services.tenant import BILL_COLUMNS, TenantService

router = APIRouter(prefix="/api/tenant", tags=["商业租户"])

service = TenantService()

CONTRACT_COLUMNS = ["合同编号", "租户名称", "铺位号", "合同开始", "合同结束", "月租金", "保证金", "status"]
LEDGER_COLUMNS = ["合同编号", "租户名称", "铺位号", "账期", "应收金额", "实收金额", "账单编号", "核销日期", "status"]
LEDGER_EXPORT_COLUMNS = ["合同编号", "租户名称", "铺位号", "账期", "应收金额", "实收金额", "账单编号", "核销日期", "状态"]


# ------------------------------------------------------------------ 租户合同
@router.get("/contracts", response_model=PageResult[dict])
def list_contracts(
    keyword: str | None = Query(default=None, description="按租户名称、铺位号或合同编号检索"),
    status: str | None = Query(default=None, description="履行中、已到期、已终止"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按租户/铺位与状态过滤租户合同；状态会先按合同起止日期自动刷新。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_contracts(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/contracts/{contract_id}", response_model=dict)
def get_contract(contract_id: int) -> dict:
    """读取单条租户合同明细；不存在时给出可读的错误说明。"""
    entry = service.get_contract(contract_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"合同 {contract_id} 不存在或已归档")
    return entry


@router.post("/contracts", response_model=ActionResult)
def create_contract(payload: EntryPayload) -> ActionResult:
    """登记租户合同：租户、铺位、起止、月租、保证金缺一不可，铺位租期重叠会被拦下。"""
    entry, message = service.create_contract(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message or "合同登记失败")
    return ActionResult(ok=True, message="租户合同已登记，铺位在租状态已更新", entry=entry)


@router.post("/contracts/{contract_id}/actions", response_model=ActionResult)
def run_contract_action(contract_id: int, payload: EntryPayload) -> ActionResult:
    """对合同执行终止；终止后铺位同步释放，其它模块不受影响。"""
    action = str(payload.values.get("action") or "").strip()
    if action != "终止合同":
        return ActionResult(ok=False, message=f"动作「{action}」不属于租户合同可执行范围")
    entry, message = service.terminate_contract(contract_id)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


# ------------------------------------------------------------------ 租金台账
@router.get("/ledger", response_model=PageResult[dict])
def list_ledger(
    keyword: str | None = Query(default=None, description="按租户名称、铺位号或账单编号检索"),
    status: str | None = Query(default=None, description="待核销、已核销"),
    booth: str | None = Query(default=None, description="按铺位号精确过滤"),
    period: str | None = Query(default=None, description="按账期 YYYY-MM 精确过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """租金台账查询：过滤口径与合计、清单导出完全一致。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_ledger(
        keyword=keyword, status=status, booth=booth, period=period, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/ledger/summary", response_model=LedgerSummary)
def ledger_summary(
    keyword: str | None = None,
    status: str | None = None,
    booth: str | None = None,
    period: str | None = None,
) -> LedgerSummary:
    """台账合计：与清单导出同源，页面上的数字和清单合计必须一致。"""
    values = service.ledger_summary(keyword=keyword, status=status, booth=booth, period=period)
    return LedgerSummary(**values)


@router.post("/ledger/generate", response_model=ActionResult)
def generate_ledger(payload: EntryPayload) -> ActionResult:
    """按合同生成租金台账；不传合同编号时为所有合同补齐缺失账期，已有账期跳过。"""
    raw_id = payload.values.get("contract_id")
    contract_id: int | None = None
    if raw_id not in (None, ""):
        try:
            contract_id = int(raw_id)
        except (TypeError, ValueError):
            return ActionResult(ok=False, message="合同编号必须是数字")
    result, message = service.generate_ledger(contract_id)
    if result is None:
        return ActionResult(ok=False, message=message or "台账生成失败")
    return ActionResult(
        ok=True,
        message=f"租金台账已生成：新增 {result['created']} 条，已存在账期跳过 {result['skipped']} 条",
    )


@router.post("/ledger/import-bills", response_model=BillImportResult)
def import_bills(payload: EntryPayload) -> BillImportResult:
    """导入一批账单 CSV 做核销：逐行校验，出错只跳过该行，其余继续入账。"""
    file_name = str(payload.values.get("file_name") or "账单导入.csv").strip()
    content = str(payload.values.get("content") or "")
    if not content.strip():
        return BillImportResult(file_name=file_name, results=[])
    values = service.import_bills(file_name, content)
    return BillImportResult(**values)


@router.get("/ledger/import-template")
def download_bill_template() -> StreamingResponse:
    """下载账单导入模板：列顺序与逐行校验要求的列保持一致。"""
    buffer = io.StringIO()
    buffer.write("﻿")
    writer = csv.writer(buffer)
    writer.writerow(BILL_COLUMNS)
    writer.writerow(["B1-08", "2026-09", "BILL-202609-B108", "12000.00"])
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=bill_import_template.csv"},
    )


@router.get("/ledger/export")
def export_ledger(
    format: str = Query(default="csv", description="csv 或 json"),
    keyword: str | None = None,
    status: str | None = None,
    booth: str | None = None,
    period: str | None = None,
) -> Any:
    """另存租金台账清单：合计行与页面合计卡片使用同一份汇总数字。"""
    items, _ = service.list_ledger(
        keyword=keyword, status=status, booth=booth, period=period, page=1, size=100000
    )
    summary = service.ledger_summary(keyword=keyword, status=status, booth=booth, period=period)

    if format.lower() == "json":
        return {
            "module": "tenant_ledger",
            "total": len(items),
            "summary": summary,
            "items": items,
        }

    buffer = io.StringIO()
    buffer.write("﻿")
    writer = csv.writer(buffer)
    writer.writerow(LEDGER_EXPORT_COLUMNS)
    for row in items:
        writer.writerow([
            row.get("合同编号", ""),
            row.get("租户名称", ""),
            row.get("铺位号", ""),
            row.get("账期", ""),
            row.get("应收金额", ""),
            row.get("实收金额", ""),
            row.get("账单编号", ""),
            row.get("核销日期", ""),
            row.get("status", ""),
        ])
    writer.writerow([
        "合计", "", "", summary["count"],
        f"{summary['due_total']:.2f}",
        f"{summary['paid_total']:.2f}",
        "", "",
        f"未核销 {summary['unpaid_total']:.2f}",
    ])
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=tenant_ledger.csv"},
    )


# ------------------------------------------------------------------ 铺位状态
@router.get("/booths")
def list_booths(
    keyword: str | None = Query(default=None, description="按铺位号或租户名称检索"),
    status: str | None = Query(default=None, description="在租、空闲"),
) -> dict[str, Any]:
    """铺位在租状态跟着租户合同走：查询方式与其它模块一致，不单独维护铺位表。"""
    items = service.list_booths(keyword=keyword, status=status)
    return {"items": items, "total": len(items)}
