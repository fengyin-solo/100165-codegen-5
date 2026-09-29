"""商业租户模块的本地文件仓库。

主数据仓库 app.store 是进程内存态，重启即回落到示例数据；商业租户的合同、台账属于
真实业务数据，要求「页面重开仍然在」，因此单独落一份 JSON 文件，每次写操作后立即
刷盘。为避免半写入把数据写坏，先写临时文件再原子替换。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

# 默认落在后端根目录下；容器里可通过 TENANT_DATA_FILE 指到可写卷。
DEFAULT_DATA_FILE = Path(__file__).resolve().parent.parent / "tenant_data.json"
DATA_FILE = Path(os.environ.get("TENANT_DATA_FILE") or DEFAULT_DATA_FILE)


class TenantStore:
    """合同与租金台账两张表，外加各自主键计数的 JSON 持久化。"""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DATA_FILE
        self._data: dict[str, Any] | None = None

    def _load(self) -> dict[str, Any]:
        if self._data is not None:
            return self._data
        if self.path.exists():
            try:
                with self.path.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    data.setdefault("contracts", [])
                    data.setdefault("ledgers", [])
                    self._data = data
                    return data
            except (json.JSONDecodeError, OSError):
                # 文件损坏时不要把进程带崩，回落初始数据并在首次写入时覆盖。
                pass
        from app.tenant_seed import build_initial_data

        self._data = build_initial_data()
        self._flush()
        return self._data

    def _flush(self) -> None:
        assert self._data is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=self.path.name, suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle, ensure_ascii=False, indent=2)
            os.replace(tmp_name, self.path)
        except BaseException:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
            raise

    @property
    def contracts(self) -> list[dict[str, Any]]:
        return self._load()["contracts"]

    @property
    def ledgers(self) -> list[dict[str, Any]]:
        return self._load()["ledgers"]

    def next_contract_id(self) -> int:
        rows = self.contracts
        return max((int(row.get("id", 0)) for row in rows), default=0) + 1

    def next_ledger_id(self) -> int:
        rows = self.ledgers
        return max((int(row.get("id", 0)) for row in rows), default=0) + 1

    def find_contract(self, contract_id: int) -> dict[str, Any] | None:
        for row in self.contracts:
            if int(row.get("id", 0)) == contract_id:
                return row
        return None

    def find_ledger(self, ledger_id: int) -> dict[str, Any] | None:
        for row in self.ledgers:
            if int(row.get("id", 0)) == ledger_id:
                return row
        return None

    def save(self) -> None:
        """业务层改完数据后统一调用落盘。"""
        if self._data is None:
            return
        self._flush()


tenant_store = TenantStore()
