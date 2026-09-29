"""数据仓库：给每个业务模块准备一份可筛选、可流转的数据。

大多数模块只在内存里放示例数据；商业租户（合同、租金台账）是真实业务录入，
通过 JSON 文件落盘，页面重开、服务重启之后仍然在。真实项目里这里会换成
数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any

from app.seed import SEED_ROWS

# 需要落盘的业务表：启动时若已有数据文件则覆盖示例数据，变更后原子写回。
PERSISTED_TABLES = ["tenant_contract", "tenant_ledger"]


class Store:
    def __init__(self) -> None:
        data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
        self._data_dir = data_dir
        self._persist_path = os.path.join(data_dir, "tenant_data.json")
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        self._load_persisted()

    def _load_persisted(self) -> None:
        """读取上次落盘的租户数据；文件不存在或损坏时回退到示例数据，不影响其它模块。"""
        if not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path, encoding="utf-8") as handle:
                saved = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return
        for name in PERSISTED_TABLES:
            rows = saved.get(name)
            if isinstance(rows, list):
                self._tables[name] = [dict(row) for row in rows]

    def save_persisted(self) -> None:
        """把租户两张表原子写入磁盘：先写临时文件再替换，避免写一半把旧数据冲掉。"""
        os.makedirs(self._data_dir, exist_ok=True)
        payload = {name: self._tables.get(name, []) for name in PERSISTED_TABLES}
        fd, tmp_path = tempfile.mkstemp(dir=self._data_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._persist_path)
        except OSError:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
