import csv,io,json
from flask import Blueprint,request,jsonify,Response
from app.errors import DomainError
from app.config import MAX_BYTES,DEFAULTS
from app import store
from . import service
bp=Blueprint("m8",__name__)

def _params_json(payload):
    params=payload.get("params")
    if params is None: return dict(DEFAULTS)
    if not isinstance(params,dict): raise DomainError("PARAMS","参数必须为对象")
    return {**DEFAULTS,**params}

def _form_params(value):
    try: data=json.loads(value or "{}")
    except ValueError: raise DomainError("PARAMS","参数格式错误")
    if not isinstance(data,dict): raise DomainError("PARAMS","参数必须为对象")
    return {**DEFAULTS,**data}

def _text(payload):
    raw=payload.get("text")
    if raw is not None and not isinstance(raw,str): raise DomainError("TEXT","数据必须为文本")
    return raw.encode("utf-8") if isinstance(raw,str) else None

def _parent(value):
    parent=value or store.latest_run()
    if not parent: raise DomainError("STATE","没有可参照的原批次")
    return parent

@bp.post("/api/m8")
def create():
    if request.files:
        file=request.files.get("file")
        if file is None: raise DomainError("FILE","请选择文件")
        raw=file.read(MAX_BYTES+1);params=_form_params(request.form.get("params"))
        parent=_parent(request.form.get("parent"))
    else:
        payload=request.get_json(silent=True)
        if not isinstance(payload,dict): raise DomainError("BODY","请求必须是对象")
        raw=_text(payload);params=_params_json(payload);parent=_parent(payload.get("parent"))
    if raw is None: raise DomainError("TEXT","请提供补读数据")
    return jsonify(service.build({'source':raw,'params':params,'parent':parent}))

@bp.get("/api/m8/<derived_id>")
def fetch(derived_id):
    record=store.derived_get(derived_id)
    if record is None: raise DomainError("NOT_FOUND","派生版本不存在",404)
    return jsonify(service.render(record))

@bp.post("/api/m8/<derived_id>/check")
def check(derived_id):
    payload=request.get_json(silent=True) or {}
    if not isinstance(payload,dict): raise DomainError("BODY","请求必须是对象")
    params=_params_json(payload)
    if payload.get("tariffs") is not None: params["tariffs"]=payload["tariffs"]
    return jsonify(service.reconcile({'derived_id':derived_id,'params':params}))

@bp.post("/api/m8/<derived_id>/activate")
def activate(derived_id):
    return jsonify(service.activate({'derived_id':derived_id}))

@bp.post("/api/m8/<derived_id>/restore")
def restore(derived_id):
    """Restore an older bill. Defaults to the ledger this station used before the
    last switch, falling back to the original batch this version came from."""
    record=store.derived_get(derived_id)
    if record is None: raise DomainError("NOT_FOUND","派生版本不存在",404)
    payload=request.get_json(silent=True) or {}
    target=payload.get("ledger") or _previous(record)
    current=store.restore(record["station"],target)
    return jsonify({'station':record["station"],'current':current})

def _previous(record):
    for row in store.switch_history(record["station"],50):
        if row["previous_id"] and row["previous_id"]!=record["id"]: return row["previous_id"]
    return record["parent"]

@bp.get("/api/m8")
def listing():
    return jsonify({'derived':store.derived_list(),'currents':store.currents(),
                    'history':store.switch_history()})

@bp.get("/api/m8/<derived_id>/evidence.csv")
def evidence(derived_id):
    record=store.derived_get(derived_id)
    if record is None: raise DomainError("NOT_FOUND","派生版本不存在",404)
    rendered=service.render(record);base=rendered["original"];payload=record["payload"] or {}
    current=rendered.get("current") or {}
    stream=io.StringIO(newline="");writer=csv.writer(stream)
    writer.writerow(["分类","站点","主键","开始","结束","电量 kWh","来源","原因码","依据"])
    for row in payload.get("segments",[]):
        writer.writerow(["合并后读数",record["station"],row.get("origin_id",""),row.get("start",""),
                         row.get("end",""),row.get("energy",""),row.get("source",""),
                         "",f"派生版本 {record['id']}"])
    for row in payload.get("isolated",[]):
        writer.writerow(["重叠隔离",record["station"],row.get("key",""),row.get("start",""),
                         row.get("end",""),row.get("energy",""),row.get("source",""),
                         row.get("code",""),row.get("detail","")])
    for row in payload.get("quarantine",[]):
        writer.writerow(["补读隔离",record["station"],row.get("key",""),"","","","",
                         row.get("code",""),row.get("detail",row.get("reason",""))])
    for row in base.get("loss_balances",[]):
        writer.writerow(["原批次损耗",row.get("station",""),"","","",row.get("loss_kwh",""),"",
                         row.get("state",""),f"原批次 {base['run_id']}"])
    for row in base.get("bills",[]):
        writer.writerow(["原批次账单",row.get("station",""),row.get("order",""),"","",
                         row.get("amount",""),"","",f"账单 {row.get('bill','')} 差额 {row.get('delta','')}"])
    result=(payload.get("result") or {})
    for row in result.get("loss_balances",[]):
        writer.writerow(["当前账损耗",row.get("station",""),"","","",row.get("loss_kwh",""),"",
                         row.get("state",""),f"派生版本 {record['id']}"])

    writer.writerow(["当前账",record["station"],current.get("ledger_id",""),"","","","",
                     current.get("ledger_kind",""),"唯一可结算结果"])
    return Response("﻿"+stream.getvalue(),content_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition":"attachment; filename=derived-evidence.csv"})
