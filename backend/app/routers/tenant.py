"""商业租户接口：租户合同、租金台账（生成/导入核销/查询/导出）、铺位在租状态。

约定与其它模块保持一致：列表返回 { items, total, page, size }，动作返回 { ok, message }；
额外在台账列表与导出里带同一份 summary，保证清单合计与页面数字同源。
"""
from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.schemas import ActionResult, PageResult
from app.services.tenant import LEDGER_FIELDS, TenantService

router = APIRouter(prefix="/api/tenant", tags=["商业租户"])

service = TenantService()

CONTRACT_COLUMNS = ["合同编号", "租户名称", "铺位号", "合同开始", "合同截止", "月租金", "保证金", "在租状态"]
BOOTH_COLUMNS = ["铺位号", "在租状态", "租户名称", "合同编号", "合同开始", "合同截止", "月租金", "保证金"]


class BillTextPayload(BaseModel):
    """账单文本导入：给不方便走 multipart 的调用方留的入口，内容仍是 CSV。"""

    content: str
    filename: str | None = None


def _paginate(items: list[dict[str, Any]], page: int, size: int) -> list[dict[str, Any]]:
    start = max(page - 1, 0) * size
    return items[start:start + size]


# ---------------- 租户合同 ----------------
@router.get("/contracts", response_model=PageResult[dict])
def list_contracts(
    keyword: str | None = Query(default=None, description="按租户名称、铺位号或合同编号检索"),
    page: int = 1,
    size: int = 200,
) -> PageResult[dict]:
    """合同数量通常不多，默认一页给全；铺位在租状态作为字段一并返回。"""
    if size > 2000:
        raise HTTPException(status_code=400, detail="每页最多 2000 条")
    items = service.list_contracts(keyword=keyword)
    return PageResult(items=_paginate(items, page, size), total=len(items), page=page, size=size)


@router.get("/contracts/{contract_id}", response_model=dict)
def get_contract(contract_id: int) -> dict:
    entry = service.get_contract(contract_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"合同 {contract_id} 不存在")
    return entry


@router.post("/contracts", response_model=ActionResult)
def create_contract(payload: dict[str, Any]) -> ActionResult:
    values = payload.get("values", payload) if isinstance(payload, dict) else {}
    entry, missing = service.create_contract(values)
    if missing:
        return ActionResult(ok=False, message=f"缺少或存在不合法字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="租户合同已登记，租金台账已生成", entry=entry)


@router.put("/contracts/{contract_id}", response_model=ActionResult)
def update_contract(contract_id: int, payload: dict[str, Any]) -> ActionResult:
    values = payload.get("values", payload) if isinstance(payload, dict) else {}
    entry, message = service.update_contract(contract_id, values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/contracts/{contract_id}/actions", response_model=ActionResult)
def contract_action(contract_id: int, payload: dict[str, Any]) -> ActionResult:
    action = str((payload or {}).get("action") or "").strip()
    if action == "终止合同":
        entry, message = service.terminate_contract(contract_id)
    elif action == "生成台账":
        entry = service.get_contract(contract_id)
        _, message = service.generate_ledgers(contract_id)
    else:
        return ActionResult(ok=False, message=f"动作「{action}」不属于租户合同可执行范围")
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


# ---------------- 租金台账 ----------------
@router.get("/ledgers")
def list_ledgers(
    keyword: str | None = Query(default=None, description="按租户名称、合同编号或铺位号检索"),
    status: str | None = Query(default=None, description="已核销、待核销"),
    period: str | None = Query(default=None, description="账期，YYYY-MM"),
    booth: str | None = Query(default=None, description="铺位号"),
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """台账分页列表；summary 始终按筛选后的全量数据计算，不受分页影响。"""
    if size > 2000:
        raise HTTPException(status_code=400, detail="每页最多 2000 条")
    all_items, summary = service.list_ledgers(keyword=keyword, status=status, period=period, booth=booth)
    return {
        "items": _paginate(all_items, page, size),
        "total": len(all_items),
        "page": page,
        "size": size,
        "summary": summary,
    }


@router.post("/ledgers/generate", response_model=ActionResult)
def generate_ledgers(payload: dict[str, Any] | None = None) -> ActionResult:
    """按合同生成台账：指定合同编号/id 只补一份；不指定则补齐全部合同。"""
    payload = payload or {}
    contract_id = payload.get("contract_id")
    if contract_id is not None:
        _, message = service.generate_ledgers(int(contract_id))
        return ActionResult(ok=True, message=message)
    created_total = 0
    messages: list[str] = []
    for contract in service.list_contracts():
        created, message = service.generate_ledgers(int(contract["id"]))
        created_total += len(created)
        messages.append(message)
    return ActionResult(ok=True, message=f"全部合同台账已补齐，新增 {created_total} 期")


@router.post("/ledgers/import")
async def import_ledger_bills(file: UploadFile = File(..., description="账单 CSV 文件")) -> dict[str, Any]:
    """上传账单 CSV 核销：表头缺列整文件拒绝；行级问题逐行提示并只跳过该行。"""
    raw = await file.read()
    records, problems = service.parse_bill_file(raw, file.filename or "")
    if problems:
        raise HTTPException(status_code=400, detail=problems[0])
    return service.import_bills(records)


@router.post("/ledgers/import-text")
def import_ledger_bills_text(payload: BillTextPayload) -> dict[str, Any]:
    """文本方式提交账单 CSV，口径与文件上传完全一致。"""
    records, problems = service.parse_bill_file(payload.content, payload.filename or "")
    if problems:
        raise HTTPException(status_code=400, detail=problems[0])
    return service.import_bills(records)


def _filtered_ledgers(
    keyword: str | None, status: str | None, period: str | None, booth: str | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return service.list_ledgers(keyword=keyword, status=status, period=period, booth=booth)


@router.get("/ledgers/export")
def export_ledgers(
    keyword: str | None = None,
    status: str | None = None,
    period: str | None = None,
    booth: str | None = None,
) -> StreamingResponse:
    """另存租金台账清单（CSV）：筛选口径、合计与台账页完全一致，末行附合计。"""
    items, summary = _filtered_ledgers(keyword, status, period, booth)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(LEDGER_FIELDS)
    for row in items:
        writer.writerow([row.get(field, "") for field in LEDGER_FIELDS])
    writer.writerow([])
    writer.writerow([
        "合计", "", "", f"共 {summary['总期数']} 期",
        summary["应收合计"], summary["已核销合计"],
        f"待核销 {summary['待核销期数']} 期", summary["待核销合计"], "",
    ])
    data = "﻿" + buffer.getvalue()
    return StreamingResponse(
        io.BytesIO(data.encode("utf-8")),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=rent-ledger.csv"},
    )


@router.get("/ledgers/export-json")
def export_ledgers_json(
    keyword: str | None = None,
    status: str | None = None,
    period: str | None = None,
    booth: str | None = None,
) -> dict[str, Any]:
    """清单的 JSON 版本：summary 与 CSV 末行、页面卡片同源。"""
    items, summary = _filtered_ledgers(keyword, status, period, booth)
    return {"module": "tenant-ledger", "columns": LEDGER_FIELDS, "total": len(items), "summary": summary, "items": items}


# ---------------- 铺位在租状态 ----------------
@router.get("/booths", response_model=PageResult[dict])
def list_booths(
    booth: str | None = Query(default=None, description="按铺位号检索"),
    status: str | None = Query(default=None, description="在租、未到期、已到期、已终止"),
    page: int = 1,
    size: int = 200,
) -> PageResult[dict]:
    """铺位在租状态由合同实时推导：合同在期内即「在租」，终止/到期立即反映。"""
    if size > 2000:
        raise HTTPException(status_code=400, detail="每页最多 2000 条")
    items = service.list_booths(booth=booth, status=status)
    return PageResult(items=_paginate(items, page, size), total=len(items), page=page, size=size)
