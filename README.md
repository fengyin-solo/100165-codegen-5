# 机场地面保障调度平台

面向机场机坪运行的航班保障、机位资源、廊桥对接、除冰加注、行李装卸与保障结算的一体化地面调度后台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 航班计划 | `flight` | 航班计划 | 航班号、执行日期、机型 |
| 机位资源 | `stand` | 机位 | 机位编号、机位类别、所属区域 |
| 机坪巡查 | `apron` | 巡查单 | 巡查单号、巡查区域、巡查人员 |
| 廊桥对接 | `bridge` | 对接任务 | 对接单号、关联航班、廊桥编号 |
| 除冰作业 | `deicing` | 除冰单 | 除冰单号、关联航班、除冰方式 |
| 航油加注 | `fueling` | 加注单 | 加注单号、关联航班、加注车号 |
| 行李装卸 | `baggage` | 装卸单 | 装卸单号、关联航班、行李件数 |
| 货邮装载 | `cargo` | 装载单 | 装载单号、关联航班、货邮重量 |
| 航空配餐 | `catering` | 配餐单 | 配餐单号、关联航班、餐食份数 |
| 摆渡接送 | `shuttle` | 摆渡任务 | 任务编号、关联航班、车辆编号 |
| 航空器牵引 | `towing` | 牵引任务 | 牵引编号、关联航班、牵引车号 |
| 载重平衡 | `loadsheet` | 配载单 | 配载单号、关联航班、计算重量 |
| 通行证件 | `permit` | 通行证件 | 证件编号、持证人员、所属单位 |
| 保障车辆 | `gse` | 保障车辆 | 车辆编号、车辆类别、适用作业 |
| 安全监察 | `safety` | 监察记录 | 监察编号、监察区域、监察事项 |
| 保障协议 | `agreement` | 保障协议 | 协议编号、服务单位、保障项目 |
| 保障结算 | `settlement` | 结算单 | 结算单号、关联协议、结算周期 |
| 资质培训 | `training` | 培训记录 | 培训编号、培训主题、培训对象 |
| 商业租户 | `tenant` | 租户合同 / 租金台账 / 铺位 | 租户名称、铺位号、合同起止、月租金、保证金 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 商业租户

- 合同维护：租户名称、铺位号、合同起止、月租金、保证金；同一铺位不允许同时存在两份
  未终止合同。登记或编辑合同后自动按月生成租金台账，重复生成不会覆盖已核销记录。
- 账单导入：CSV 必须含 `铺位号、账期、账单编号、金额` 四列（支持常见表头别名，
  如「店铺号 / 账单月份 / 账单号 / 账单金额」）。表头缺列整文件拒绝；行内缺列内容、
  金额与合同月租金不一致、同一账期重复送单（含同一文件内重复）时，只跳过该行并在导入
  结果里逐行说明，其余行照常核销入账。
- 租金台账清单可另存为 CSV，末行合计与页面卡片同一份 `summary`，筛选口径也完全一致。
- 铺位在租状态（在租 / 未到期 / 已到期 / 已终止）完全由合同起止与终止情况推导。
- 商业租户数据写入 `backend/tenant_data.json`（可用环境变量 `TENANT_DATA_FILE` 改位置），
  进程重启后仍在；其它模块仍走内存示例数据，查询方式不变。
- 后端冒烟测试：`TENANT_DATA_FILE=$(mktemp) .venv/bin/python -m tests.test_tenant_smoke`。
