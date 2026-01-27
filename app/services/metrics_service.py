# app/services/metrics_service.py
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Literal, Dict, Any, List, Tuple
from app.core.db import get_db

PeriodParam = Literal["daily","weekly","monthly"]

# === Configuración SLA por prioridad (horas) ===
SLA_HOURS_BY_PRIORITY = {
    "Alta": 24,
    "Media": 72,
    "Baja": 120,
}

OPEN_SET = {"Pendiente","En progreso","En revisión"}

def _period_bounds(period: PeriodParam) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    if period == "daily":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    elif period == "weekly":
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
    else:  # monthly
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
    return start, end

def _alias_period(period_alias: str) -> PeriodParam:
    alias = (period_alias or "").lower()
    if alias in ("day", "daily"): return "daily"
    if alias in ("week", "weekly"): return "weekly"
    if alias in ("month", "monthly"): return "monthly"
    return "daily"

def _series_buckets(period: PeriodParam, start: datetime, end: datetime) -> List[datetime]:
    step = timedelta(days=1)
    if period == "daily":
        # 24 horas (por hora)
        return [start + timedelta(hours=i) for i in range(24)]
    # semanal/mensual: por día
    days = int((end - start).total_seconds() // 86400)
    return [start + timedelta(days=i) for i in range(days)]

def _label_for(dt: datetime, period: PeriodParam) -> str:
    if period == "daily":
        return dt.strftime("%H:00")
    return dt.strftime("%Y-%m-%d")

async def summary(period: PeriodParam, extended: bool = False) -> Dict[str, Any]:
    db = get_db()
    start, end = _period_bounds(period)

    # --- core KPIs (como ya entregamos) ---
    new_count = await db.requests.count_documents({ "created_at": {"$gte": start, "$lt": end} })
    finished_count = await db.requests.count_documents({ "status": "Finalizada", "completion_date": {"$gte": start, "$lt": end} })
    pending_now = await db.requests.count_documents({ "status": {"$in": list(OPEN_SET)} })
    in_review_now = await db.requests.count_documents({ "status": "En revisión" })

    pipeline_avg = [
        {"$match": {"status": "Finalizada","completion_date": {"$gte": start, "$lt": end},"created_at": {"$ne": None}}},
        {"$project": {"_id": 0, "cycle_hours": {"$divide": [{"$subtract": ["$completion_date","$created_at"]}, 1000*60*60]}}},
        {"$group": {"_id": None, "avg": {"$avg": "$cycle_hours"}}},
    ]
    agg_avg = await db.requests.aggregate(pipeline_avg).to_list(1)
    avg_cycle_hours = round(float(agg_avg[0]["avg"]), 2) if agg_avg else 0.0

    total_requests = await db.requests.estimated_document_count()
    assigned_total = await db.requests.count_documents({"assigned_to": {"$ne": None}})
    unassigned_total = total_requests - assigned_total
    new_last_24h = await db.requests.count_documents({"created_at": {"$gte": datetime.now(timezone.utc) - timedelta(hours=24)}})

    # productividad por técnico (idéntico a antes)
    OPEN = ["Pendiente","En progreso","En revisión"]
    assigned_pipeline = [
        {"$match": {"assigned_to": {"$ne": None}}},
        {"$group": {"_id": {"id":"$assigned_to", "name":"$assigned_to_name"}, "assigned_total": {"$sum": 1}}},
    ]
    pending_pipeline = [
        {"$match": {"status": {"$in": OPEN}, "assigned_to": {"$ne": None}}},
        {"$group": {"_id": {"id":"$assigned_to", "name":"$assigned_to_name"}, "pending_now": {"$sum": 1}}},
    ]
    attended_pipeline = [
        {"$match": {"status": "Finalizada","completion_date": {"$gte": start, "$lt": end},"assigned_to": {"$ne": None}}},
        {"$group": {"_id": {"id":"$assigned_to", "name":"$assigned_to_name"}, "attended_period": {"$sum": 1}}},
    ]
    review_pipeline = [
        {"$match": {"status": "En revisión","completion_date": {"$gte": start, "$lt": end},"assigned_to": {"$ne": None}}},
        {"$group": {"_id": {"id":"$assigned_to", "name":"$assigned_to_name"}, "attended_period": {"$sum": 1}}},
    ]
    assigned = await db.requests.aggregate(assigned_pipeline).to_list(None)
    pend = await db.requests.aggregate(pending_pipeline).to_list(None)
    att = await db.requests.aggregate(attended_pipeline).to_list(None)
    rev = await db.requests.aggregate(review_pipeline).to_list(None)
    assigned_map: Dict[str, Dict[str, Any]] = {}
    for a in assigned:
        k = a["_id"]["id"] or "N/D"
        assigned_map[k] = {"tech_id": k,"tech_name": a["_id"].get("name") or "No asignado","assigned_total": int(a["assigned_total"]),"pending_now": 0,"attended_period": 0}
    for p in pend:
        k = p["_id"]["id"] or "N/D"
        assigned_map.setdefault(k, {"tech_id": k,"tech_name": p["_id"].get("name") or "No asignado","assigned_total": 0,"pending_now": 0,"attended_period": 0})
        assigned_map[k]["pending_now"] = int(p["pending_now"])
    for a in att:
        k = a["_id"]["id"] or "N/D"
        assigned_map.setdefault(k, {"tech_id": k,"tech_name": a["_id"].get("name") or "No asignado","assigned_total": 0,"pending_now": 0,"attended_period": 0})
        assigned_map[k]["attended_period"] = int(a["attended_period"])
    for r in rev:
        k = r["_id"]["id"] or "N/D"
        assigned_map.setdefault(k, {"tech_id": k,"tech_name": r["_id"].get("name") or "No asignado","assigned_total": 0,"pending_now": 0,"attended_period": 0})
        assigned_map[k]["attended_period"] = int(r["attended_period"])
    productivity_by_tech = sorted(assigned_map.values(), key=lambda x: (-x["attended_period"], x["tech_name"]))

    result: Dict[str, Any] = {
        "period": period,
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "new": new_count,
        "finished": finished_count,
        "pending_now": pending_now,
        "in_review": in_review_now,
        "avg_cycle_hours": avg_cycle_hours,
        "totals": {
            "total_requests": total_requests,
            "assigned_total": assigned_total,
            "unassigned_total": unassigned_total,
            "new_last_24h": new_last_24h,
        },
        "productivity_by_tech": productivity_by_tech,
    }

    if not extended:
        return result

    # ========== EXTENDIDO ==========
    # 1) Tiempo promedio en cada estado (en horas) para tickets que tuvieron ese estado dentro del rango.
    #    Usamos state_history ordenado y calculamos del evento 'to_status' hasta el siguiente cambio, o end/now.
    time_pipeline = [
        {"$match": {"state_history.0": {"$exists": True}}},
        {"$project": {"state_history": 1, "created_at": 1, "status": 1, "completion_date": 1}},
    ]
    docs = await db.requests.aggregate(time_pipeline).to_list(None)
    per_status_sum: Dict[str, float] = {"Pendiente":0.0,"En progreso":0.0,"En revisión":0.0}
    per_status_n: Dict[str, int] = {"Pendiente":0,"En progreso":0,"En revisión":0}
    for d in docs:
        hist = sorted(d.get("state_history", []), key=lambda x: x.get("at"))
        for i, ev in enumerate(hist):
            st = ev.get("to_status")
            if st not in per_status_sum:  # ignoramos Finalizada/Rechazada en este corte
                continue
            t0 = ev.get("at")
            if not t0: continue
            # si el siguiente evento está fuera del periodo, limitamos
            t1 = hist[i+1]["at"] if i+1 < len(hist) else (d.get("completion_date") or datetime.now(timezone.utc))
            # recorte al rango consultado
            seg_start = max(t0, start)
            seg_end = min(t1, end)
            if seg_end <= seg_start:
                continue
            hours = (seg_end - seg_start).total_seconds()/3600.0
            per_status_sum[st] += hours
            per_status_n[st] += 1
    avg_time_by_status = {k: round(per_status_sum[k]/per_status_n[k], 2) if per_status_n[k] else 0.0 for k in per_status_sum.keys()}

    # 2) Rebotes En revisión → En progreso por técnico (quien ejecutó el cambio) en el periodo
    bounce_pipeline = [
        {"$match": {"changed_at": {"$gte": start, "$lt": end}}},
        {"$sort": {"changed_at": 1}},
        {"$group": {"_id": "$ticket_id", "events": {"$push": {"estado":"$estado","changed_by":"$changed_by"}}}},
        {"$project": {
            "bounces": {
                "$size": {
                    "$filter": {
                        "input": {
                            "$zip": {
                                "inputs": ["$events", {"$concatArrays":[[{"estado":None}],"$events"]}],
                                "useLongestLength": False
                            }
                        },
                        "as": "pair",
                        "cond": {"$and":[
                            {"$eq":[{"$arrayElemAt":["$$pair",0,"estado"]},"En progreso"]},
                            {"$eq":[{"$arrayElemAt":["$$pair",1,"estado"]},"En revisión"]}
                        ]}
                    }
                }
            },
            "events": 1
        }},
    ]
    # La pipeline anterior detecta pares consecutivos; hacemos conteo por usuario abajo.
    rows = await db.ticket_status_events.find({"changed_at":{"$gte":start,"$lt":end}}).sort("changed_at",1).to_list(None)
    rebotes_by_user: Dict[str,int] = {}
    last_state_by_ticket: Dict[str,str] = {}
    for ev in rows:
        tid = ev["ticket_id"]; st = ev["estado"]; by = ev.get("changed_by") or "N/D"
        prev = last_state_by_ticket.get(tid)
        if prev == "En revisión" and st == "En progreso":
            rebotes_by_user[by] = rebotes_by_user.get(by,0)+1
        last_state_by_ticket[tid] = st
    # mapear nombres
    users_cache = {u["id"]: u async for u in db.users.find({}, {"id":1,"full_name":1})}
    bounces_by_tech = [
        {"tech_id": uid, "tech_name": users_cache.get(uid,{}).get("full_name","N/D"), "returns_from_review": cnt}
        for uid, cnt in sorted(rebotes_by_user.items(), key=lambda kv: -kv[1])
    ]

    # 3) Feedback 👍/👎 por técnico y por departamento (del requester)
    fb_by_tech_pipeline = [
        {"$match": {"feedback.rating": {"$in": ["up","down"]}, "assigned_to": {"$ne": None}}},
        {"$group": {"_id": {"id":"$assigned_to","name":"$assigned_to_name","rating":"$feedback.rating"}, "count": {"$sum": 1}}},
    ]
    fb_rows = await db.requests.aggregate(fb_by_tech_pipeline).to_list(None)
    fb_map: Dict[str, Dict[str, int]] = {}
    for r in fb_rows:
        tid = r["_id"]["id"] or "N/D"
        name = r["_id"]["name"] or "N/D"
        rating = r["_id"]["rating"]
        fb_map.setdefault(tid, {"tech_id": tid, "tech_name": name, "up": 0, "down": 0})
        fb_map[tid][rating] = int(r["count"])
    feedback_by_tech = sorted(fb_map.values(), key=lambda x: (-(x["up"]-x["down"]), -x["up"]))

    fb_by_dept_pipeline = [
        {"$match": {"feedback.rating": {"$in": ["up","down"]}}},
        {"$group": {"_id": {"dept":"$department","rating":"$feedback.rating"}, "count": {"$sum": 1}}},
    ]
    fb_dept_rows = await db.requests.aggregate(fb_by_dept_pipeline).to_list(None)
    by_dept: Dict[str, Dict[str, int]] = {}
    for r in fb_dept_rows:
        dept = r["_id"]["dept"] or "N/D"
        rating = r["_id"]["rating"]
        by_dept.setdefault(dept, {"department": dept, "up": 0, "down": 0})
        by_dept[dept][rating] = int(r["count"])
    feedback_by_department = sorted(by_dept.values(), key=lambda x: (-(x["up"]-x["down"]), -x["up"]))

    # 4) Vencidos vs en SLA por prioridad (usa SLA_HOURS_BY_PRIORITY)
    # vencido si (Finalizada y completion_date > created_at + SLA) o (abierta y now > created_at + SLA)
    now = datetime.now(timezone.utc)
    sla_docs = await db.requests.find({}, {"priority":1,"created_at":1,"status":1,"completion_date":1}).to_list(None)
    sla_counters = {p: {"priority": p, "in_sla": 0, "overdue": 0} for p in SLA_HOURS_BY_PRIORITY.keys()}
    for d in sla_docs:
        pr = d.get("priority") or "Media"
        if pr not in sla_counters: continue
        delta = timedelta(hours=SLA_HOURS_BY_PRIORITY[pr])
        deadline = (d.get("created_at") or now) + delta
        end_time = d.get("completion_date") or now
        if end_time > deadline:
            sla_counters[pr]["overdue"] += 1
        else:
            sla_counters[pr]["in_sla"] += 1
    sla_by_priority = list(sla_counters.values())

    # 5) Tendencia recibidos vs resueltos (serie temporal)
    buckets = _series_buckets(period, start, end)
    labels = [_label_for(b, period) for b in buckets]
    received_series = [0 for _ in buckets]
    resolved_series = [0 for _ in buckets]

    if period == "daily":
        # por hora
        rec_rows = await db.requests.find({"created_at":{"$gte":start,"$lt":end}}, {"created_at":1}).to_list(None)
        fin_rows = await db.requests.find({"status":"Finalizada","completion_date":{"$gte":start,"$lt":end}}, {"completion_date":1}).to_list(None)
        for r in rec_rows:
            idx = (r["created_at"] - start).seconds // 3600
            if 0 <= idx < len(received_series): received_series[idx] += 1
        for r in fin_rows:
            idx = (r["completion_date"] - start).seconds // 3600
            if 0 <= idx < len(resolved_series): resolved_series[idx] += 1
    else:
        # por día
        rec_rows = await db.requests.find({"created_at":{"$gte":start,"$lt":end}}, {"created_at":1}).to_list(None)
        fin_rows = await db.requests.find({"status":"Finalizada","completion_date":{"$gte":start,"$lt":end}}, {"completion_date":1}).to_list(None)
        for r in rec_rows:
            idx = int((r["created_at"] - start).total_seconds() // 86400)
            if 0 <= idx < len(received_series): received_series[idx] += 1
        for r in fin_rows:
            idx = int((r["completion_date"] - start).total_seconds() // 86400)
            if 0 <= idx < len(resolved_series): resolved_series[idx] += 1

    trend = {"labels": labels, "received": received_series, "resolved": resolved_series}

    # 6) Distribución por tipo / nivel / departamento
    def _group_count(field: str):
        return [
            {"$group": {"_id": {"k": f"${field}"}, "count": {"$sum": 1}}},
            {"$project": {"_id": 0, "name": "$_id.k", "count": 1}},
            {"$sort": {"count": -1, "name": 1}},
        ]
    dist_type = await db.requests.aggregate(_group_count("type")).to_list(None)
    dist_level = await db.requests.aggregate(_group_count("level")).to_list(None)
    dist_dept = await db.requests.aggregate(_group_count("department")).to_list(None)

    result["extended"] = {
        "avg_time_by_status": avg_time_by_status,
        "returns_from_review_by_tech": bounces_by_tech,
        "feedback": {
            "by_tech": feedback_by_tech,
            "by_department": feedback_by_department,
        },
        "sla_by_priority": sla_by_priority,
        "trend_received_vs_resolved": trend,
        "distribution": {
            "by_type": dist_type,
            "by_level": dist_level,
            "by_department": dist_dept,
        },
        "config": {
            "sla_hours_by_priority": SLA_HOURS_BY_PRIORITY,
        }
    }
    return result

async def summary_alias(period_alias: str, extended: bool = False) -> Dict[str, Any]:
    return await summary(_alias_period(period_alias), extended=extended)

# === Funciones auxiliares para compatibilidad con endpoints ===
from datetime import datetime
from app.core.db import get_db

async def productividad_por_tecnico(start_date: datetime, end_date: datetime):
    """
    Devuelve la productividad por técnico entre start_date y end_date.
    Reutiliza el cálculo que ya hace summary(extended=True).
    """
    data = await summary("daily", extended=True)
    return {"productivity_by_tech": data.get("productivity_by_tech", [])}

async def tasa_reapertura(start_date: datetime, end_date: datetime):
    """
    Calcula la tasa de reapertura de tickets entre start_date y end_date.
    """
    db = get_db()
    total = await db.requests.count_documents({
        "created_at": {"$gte": start_date, "$lt": end_date}
    })
    reabiertos = await db.requests.count_documents({
        "created_at": {"$gte": start_date, "$lt": end_date},
        "history.status": {"$in": ["Reabierto"]}
    })
    return reabiertos / total if total > 0 else 0.0
