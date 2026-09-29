"""业务模块路由汇总。

这里统一按别名导入再暴露 ROUTERS：模块名有可能和内置名撞车（某个业务模块就叫 dict、list
这种名字时），按名字直接 import 会把内置类型覆盖掉，函数注解在运行时求值就会报
'module' object is not subscriptable。
"""
from __future__ import annotations

from app.routers import flight as router_flight
from app.routers import stand as router_stand
from app.routers import apron as router_apron
from app.routers import bridge as router_bridge
from app.routers import deicing as router_deicing
from app.routers import fueling as router_fueling
from app.routers import baggage as router_baggage
from app.routers import cargo as router_cargo
from app.routers import catering as router_catering
from app.routers import shuttle as router_shuttle
from app.routers import towing as router_towing
from app.routers import loadsheet as router_loadsheet
from app.routers import permit as router_permit
from app.routers import gse as router_gse
from app.routers import safety as router_safety
from app.routers import agreement as router_agreement
from app.routers import settlement as router_settlement
from app.routers import training as router_training
from app.routers import tenant as router_tenant

ROUTERS = [router_flight, router_stand, router_apron, router_bridge, router_deicing, router_fueling, router_baggage, router_cargo, router_catering, router_shuttle, router_towing, router_loadsheet, router_permit, router_gse, router_safety, router_agreement, router_settlement, router_training, router_tenant]
