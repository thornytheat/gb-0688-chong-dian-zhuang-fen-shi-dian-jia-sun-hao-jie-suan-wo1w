import os,sqlite3,json
from datetime import datetime,timezone
from pathlib import Path
from app.errors import DomainError
SCHEMA="""
CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY,payload TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,review TEXT NOT NULL DEFAULT '待复核');
CREATE TABLE IF NOT EXISTS derived (id TEXT PRIMARY KEY,parent TEXT NOT NULL,station TEXT NOT NULL,
  key TEXT NOT NULL UNIQUE,status TEXT NOT NULL DEFAULT '进行中',payload TEXT NOT NULL DEFAULT '{}',
  basis TEXT NOT NULL DEFAULT '{}',progress TEXT NOT NULL DEFAULT '{}',created TEXT NOT NULL,updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS current (station TEXT PRIMARY KEY,ledger_id TEXT NOT NULL,
  ledger_kind TEXT NOT NULL DEFAULT 'derived',updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS current_history (station TEXT NOT NULL,ledger_id TEXT NOT NULL,
  ledger_kind TEXT NOT NULL,previous_id TEXT,previous_kind TEXT,reason TEXT NOT NULL,changed TEXT NOT NULL);
"""
def now(): return datetime.now(timezone.utc).isoformat()
def connection():
    path=Path(os.environ.get("DATA_DIR","data"));path.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path/"runs.sqlite",timeout=15)
    db.row_factory=sqlite3.Row
    db.isolation_level=None
    db.executescript(SCHEMA)
    return db
def save(result):
    with connection() as db:
        db.execute("INSERT OR IGNORE INTO runs(id,payload) VALUES(?,?)",(result["manifest"]["run_id"],json.dumps(result,ensure_ascii=False)))
    return fetch(result["manifest"]["run_id"])
def fetch(run_id):
    with connection() as db: row=db.execute("SELECT * FROM runs WHERE id=?",(run_id,)).fetchone()
    if row is None: raise DomainError("NOT_FOUND","批次不存在",404)
    result=json.loads(row["payload"]);result["version"]=row["version"];result["review"]=row["review"]
    return result
def history():
    with connection() as db: rows=db.execute("SELECT id,version,review FROM runs ORDER BY rowid DESC LIMIT 100").fetchall()
    return [dict(row) for row in rows]
def review(run_id,version,decision):
    if decision not in ("通过","退回"): raise DomainError("REVIEW","请选择通过或退回")
    if not isinstance(version,int): raise DomainError("STALE","版本必须为整数")
    with connection() as db:
        cur=db.execute("UPDATE runs SET review=?,version=version+1 WHERE id=? AND version=?",(decision,run_id,version))
        if cur.rowcount!=1: raise DomainError("STALE","复核版本已更新",409)
    return fetch(run_id)
def has_run(run_id):
    with connection() as db: return db.execute("SELECT 1 FROM runs WHERE id=?",(run_id,)).fetchone() is not None
def latest_run():
    with connection() as db: row=db.execute("SELECT id FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()
    return row["id"] if row else None
def derived_row(row):
    if row is None: return None
    item=dict(row)
    for key in ("payload","basis","progress"): item[key]=json.loads(item[key] or "{}")
    return item
def derived_get(derived_id):
    with connection() as db: row=db.execute("SELECT * FROM derived WHERE id=?",(derived_id,)).fetchone()
    return derived_row(row)
def derived_by_key(key):
    with connection() as db: row=db.execute("SELECT * FROM derived WHERE key=?",(key,)).fetchone()
    return derived_row(row)
def derived_claim(derived_id,parent,station,key):
    stamp=now()
    with connection() as db:
        db.execute("INSERT OR IGNORE INTO derived(id,parent,station,key,status,created,updated) VALUES(?,?,?,?, '进行中',?,?)",(derived_id,parent,station,key,stamp,stamp))
    return derived_get(derived_id)
def derived_progress(derived_id,progress):
    with connection() as db:
        db.execute("UPDATE derived SET progress=?,updated=? WHERE id=?",(json.dumps(progress,ensure_ascii=False),now(),derived_id))
def derived_result(derived_id,payload,basis,status):
    with connection() as db:
        db.execute("UPDATE derived SET payload=?,basis=?,status=?,updated=? WHERE id=?",(json.dumps(payload,ensure_ascii=False),json.dumps(basis,ensure_ascii=False),status,now(),derived_id))
def derived_status(derived_id,status):
    with connection() as db:
        db.execute("UPDATE derived SET status=?,updated=? WHERE id=?",(status,now(),derived_id))
def derived_list(parent=None,station=None):
    query="SELECT * FROM derived";filters=[];args=[]
    if parent: filters.append("parent=?");args.append(parent)
    if station: filters.append("station=?");args.append(station)
    if filters: query+=" WHERE "+" AND ".join(filters)
    query+=" ORDER BY rowid DESC"
    with connection() as db: rows=db.execute(query,args).fetchall()
    return [derived_row(row) for row in rows]
def currents():
    with connection() as db: rows=db.execute("SELECT * FROM current ORDER BY station").fetchall()
    return [dict(row) for row in rows]
def current_for(station):
    with connection() as db: row=db.execute("SELECT * FROM current WHERE station=?",(station,)).fetchone()
    return dict(row) if row else None
def seed_current(station,run_id):
    """Record the original batch as the station's baseline ledger if none is set."""
    with connection() as db:
        db.execute("INSERT OR IGNORE INTO current(station,ledger_id,ledger_kind,updated) VALUES(?,?,'run',?)",(station,run_id,now()))
    return current_for(station)
def switch_history(station=None,limit=50):
    query="SELECT * FROM current_history";args=[]
    if station: query+=" WHERE station=?";args.append(station)
    query+=" ORDER BY rowid DESC LIMIT ?";args.append(limit)
    with connection() as db: rows=db.execute(query,args).fetchall()
    return [dict(row) for row in rows]
def _point(db,station,ledger_id,ledger_kind,stamp):
    db.execute("INSERT INTO current(station,ledger_id,ledger_kind,updated) VALUES(?,?,?,?) ON CONFLICT(station) DO UPDATE SET ledger_id=excluded.ledger_id,ledger_kind=excluded.ledger_kind,updated=excluded.updated",(station,ledger_id,ledger_kind,stamp))
def _drop(db,station):
    db.execute("DELETE FROM current WHERE station=?",(station,))
def _history(db,station,ledger_id,ledger_kind,previous,reason,stamp):
    db.execute("INSERT INTO current_history(station,ledger_id,ledger_kind,previous_id,previous_kind,reason,changed) VALUES(?,?,?,?,?,?,?)",
               (station,ledger_id,ledger_kind,previous["ledger_id"] if previous else None,
                previous["ledger_kind"] if previous else None,reason,stamp))
def activate(derived_id,journal=None):
    """Switch the single current ledger for a station. The caller has already
    established the previous ledger (normally the original batch) via seed_current.
    `journal` runs inside the same transaction as the new bill, so any failure
    rolls the switch back; the previous bill is then pointed at again and the
    failed version never becomes current."""
    record=derived_get(derived_id)
    if record is None: raise DomainError("NOT_FOUND","派生版本不存在",404)
    station=record["station"]
    if record["status"]=="当前": return current_for(station)
    if record["status"] not in ("待核对","已核对"): raise DomainError("STATE","只有核对通过的版本才能切换")
    previous=current_for(station)
    if previous is None: raise DomainError("STATE","请先将原批次登记为当前账")
    stamp=now()
    with connection() as db:
        try:
            db.execute("BEGIN IMMEDIATE")
            _point(db,station,derived_id,"derived",stamp)
            if journal is not None: journal(db)
            db.execute("UPDATE derived SET status='当前',updated=? WHERE id=?",(stamp,derived_id))
            if previous["ledger_kind"]=="derived" and previous["ledger_id"]!=derived_id:
                db.execute("UPDATE derived SET status='已替换',updated=? WHERE id=?",(stamp,previous["ledger_id"]))
            _history(db,station,derived_id,"derived",previous,"切换至派生版本 "+derived_id,stamp)
            db.execute("COMMIT")
        except DomainError:
            try: db.execute("ROLLBACK")
            except Exception: pass
            raise
        except Exception as exc:
            try: db.execute("ROLLBACK")
            except Exception: pass
            # Explicitly restore the prior bill; the original ledger stays queryable.
            try:
                db.execute("BEGIN IMMEDIATE")
                _point(db,station,previous["ledger_id"],previous["ledger_kind"],now())
                _history(db,station,previous["ledger_id"],previous["ledger_kind"],previous,
                         "新账写入失败，恢复旧版账单："+str(exc)[:120],now())
                db.execute("COMMIT")
            except Exception:
                try: db.execute("ROLLBACK")
                except Exception: pass
            raise DomainError("WRITE","新账写入失败，已恢复旧版账单",409)
    return current_for(station)
def restore(station,ledger_id=None,reason="手动恢复旧版账单"):
    target=ledger_id
    if target is None:
        with connection() as db: row=db.execute("SELECT previous_id,previous_kind FROM current_history WHERE station=? AND previous_id IS NOT NULL ORDER BY rowid DESC LIMIT 1",(station,)).fetchone()
        if row is None: raise DomainError("STATE","没有可恢复的旧版账单")
        target,kind=row["previous_id"],row["previous_kind"]
    else:
        if derived_get(target): kind="derived"
        elif has_run(target): kind="run"
        else: raise DomainError("STATE","旧版账单不存在")
    previous=current_for(station);stamp=now()
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            _point(db,station,target,kind,stamp)
            if kind=="derived": db.execute("UPDATE derived SET status='当前',updated=? WHERE id=?",(stamp,target))
            if previous and previous["ledger_kind"]=="derived" and previous["ledger_id"]!=target:
                db.execute("UPDATE derived SET status='已替换',updated=? WHERE id=?",(stamp,previous["ledger_id"]))
            _history(db,station,target,kind,previous,reason,stamp)
            db.execute("COMMIT")
        except Exception as exc:
            try: db.execute("ROLLBACK")
            except Exception: pass
            raise DomainError("WRITE","恢复旧版账单失败："+str(exc)[:120],409)
    return current_for(station)
