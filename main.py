from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pydantic import BaseModel
from typing import Optional
import os

from logic import (
    load_all,
    find_drug_by_name,
    search_drug_display_names,
    search_usage_names,
    calc_total,
    route_type,
    clean_code,
)

# ----------------------------------------------------------
# 起動時にマスタを一度だけメモリに読み込む
# ----------------------------------------------------------

app_state = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    data_a, data_b, data_c, long_code_set = load_all()
    app_state["data_a"] = data_a
    app_state["data_b"] = data_b
    app_state["data_c"] = data_c
    app_state["long_code_set"] = long_code_set
    print(f"マスタ読込完了: DataA={len(data_a):,}件 DataB={len(data_b):,}件 DataC={len(data_c):,}件")
    yield

app = FastAPI(title="薬剤料負担額SIM", lifespan=lifespan)

# ----------------------------------------------------------
# API
# ----------------------------------------------------------

@app.get("/api/drugs/search")
def drug_search(q: str = Query("", min_length=0)):
    data_a = app_state["data_a"]
    long_code_set = app_state["long_code_set"]
    results = search_drug_display_names(data_a, q, long_code_set, limit=20)
    return {"results": results}


@app.get("/api/drugs/info")
def drug_info(name: str = Query("")):
    data_a = app_state["data_a"]
    drug = find_drug_by_name(data_a, name)
    if drug is None:
        return {"found": False}
    return {
        "found": True,
        "code": drug["薬価基準収載医薬品コード"],
        "spec": drug["規格"],
        "route": drug["区分"],
        "route_type": route_type(drug["区分"]),
        "price": drug["薬価"],
        "is_long": clean_code(drug["薬価基準収載医薬品コード"]) in app_state["long_code_set"],
    }


@app.get("/api/usage/search")
def usage_search(q: str = Query("", min_length=0)):
    data_c = app_state["data_c"]
    results = search_usage_names(data_c, q, limit=20)
    return {"results": results}


@app.get("/api/master/stats")
def master_stats():
    return {
        "data_a": len(app_state["data_a"]),
        "data_b": len(app_state["data_b"]),
        "data_c": len(app_state["data_c"]),
        "long_code_set": len(app_state["long_code_set"]),
    }


class RpRow(BaseModel):
    before_name: str
    after_name: Optional[str] = None
    qty: float
    usage: str = ""
    special: str = ""
    days: int = 1


class CalcRequest(BaseModel):
    burden_wari: int  # 1〜10（割）
    rows: list[RpRow]


@app.post("/api/calc")
def calc(req: CalcRequest):
    data_a = app_state["data_a"]
    data_b = app_state["data_b"]
    long_code_set = app_state["long_code_set"]

    burden_rate = req.burden_wari / 10

    before_rows = []
    after_rows = []

    for r in req.rows:
        before_drug = find_drug_by_name(data_a, r.before_name)
        after_drug = find_drug_by_name(data_a, r.after_name) if r.after_name else None
        calc_after_drug = after_drug if after_drug is not None else before_drug

        before_rows.append({
            "drug": before_drug,
            "qty": r.qty,
            "usage": r.usage,
            "special": r.special,
            "days": r.days,
        })
        after_rows.append({
            "drug": calc_after_drug,
            "qty": r.qty,
            "usage": r.usage,
            "special": r.special,
            "days": r.days,
        })

    before_total = calc_total(before_rows, data_b, long_code_set, burden_rate)
    after_total = calc_total(after_rows, data_b, long_code_set, burden_rate)
    diff = after_total - before_total

    return {
        "before_total": before_total,
        "after_total": after_total,
        "diff": diff,
    }


# ----------------------------------------------------------
# UI（index.html を返す）
# ----------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index():
    html_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    with open(html_path, encoding="utf-8") as f:
        return f.read()
