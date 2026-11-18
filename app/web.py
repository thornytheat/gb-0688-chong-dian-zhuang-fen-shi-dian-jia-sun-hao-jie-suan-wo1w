from flask import render_template,request
from app import store
from app.pipeline import run
from app.config import TITLE,MODULES,STAGES,COLUMNS,SAMPLES,DEFAULTS
from app.modules.m8_derived import service as derived
def view(stage):
    if not 1<=stage<=7: return "页面不存在",404
    run_id=request.args.get("run")
    result=store.fetch(run_id) if run_id else run()
    sample=(SAMPLES/"dirty.csv").read_text(encoding="utf-8-sig")
    data=result["stages"][stage-1]
    return render_template(f"m{stage}.html",title=TITLE,modules=MODULES,stage=stage,result=result,data=data,
                           sample=sample,defaults=DEFAULTS,columns=COLUMNS,history=store.history())
def derived_view():
    """Backfill derivation page: current ledger, original batch and basis side by side."""
    derived_id=request.args.get("derived") or None
    record=None
    if derived_id:
        row=store.derived_get(derived_id)
        if row is None: return "派生版本不存在",404
        record=derived.render(row)
    run_id=request.args.get("run")
    base=store.fetch(run_id) if run_id else (store.fetch(record["parent"]) if record else run())
    sample=(SAMPLES/"backfill.csv").read_text(encoding="utf-8-sig")
    return render_template("m8.html",title=TITLE,modules=MODULES,stage=8,result=base,record=record,
                           sample=sample,defaults=DEFAULTS,columns=COLUMNS,
                           derived_list=store.derived_list(),currents=store.currents(),
                           history=store.switch_history())
