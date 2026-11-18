import hashlib,unicodedata
from datetime import datetime,time,timedelta,timezone
from decimal import Decimal as D
from app.errors import DomainError
from app.normalize import instant,rows_from
from app.modules.m2_tariffs.rules import normalize
from app.config import RULE_VERSION
DERIVE_VERSION=RULE_VERSION+"-derive-v1"
ZONE=timezone(timedelta(hours=8))
REQUIRED=['id','station','start','end','energy','unit','version','source']
SOURCES={'主表':'主表','主表读数':'主表','main':'主表','主':'主表','meter':'主表',
         '后备表':'后备表','备用表':'后备表','后备读数':'后备表','backup':'后备表','备':'后备表'}
PRIORITY={'主表':0,'后备表':1}

def source(value):
    key=unicodedata.normalize('NFKC',str(value or '')).strip().lower()
    return SOURCES.get(key)

def _cell(value):
    return unicodedata.normalize('NFKC',str(value if value is not None else '')).strip()

def _canon(field,value):
    """Semantic canonical form per field: equivalent spellings of the same reading
    (Z vs +00:00, 45 vs 45.0, fullwidth digits) must not mint a new version."""
    text=_cell(value)
    try:
        if field in ('start','end'): return instant(text).isoformat()
        if field=='energy': return str(D(text.replace(',','')).normalize())
        if field=='version': return str(int(D(text)))
    except (DomainError,ValueError,ArithmeticError):
        return text
    if field=='source':
        found=source(text)
        return found or text
    return text

def content_key(rows):
    """Stable identity of one backfill: row order, BOM and encoding must not
    create a second version for the same set of readings."""
    fields=('id','station','source','start','end','energy','unit','version')
    lines=sorted(tuple(_canon(field,row.get(field,'')) for field in fields) for row in rows)
    body="\n".join("|".join(line) for line in lines)
    return hashlib.sha256((DERIVE_VERSION+"\n"+body).encode()).hexdigest()

def key_for(parent,content,station):
    return hashlib.sha256((parent+":"+station+":"+content+":"+DERIVE_VERSION).encode()).hexdigest()

def parse(raw):
    if isinstance(raw,str): raw=raw.encode('utf-8')
    parsed=rows_from(raw,REQUIRED)
    if not parsed['raw']: raise DomainError('EMPTY','补读文件没有数据')
    stations={row['station'].strip() for row in parsed['raw'] if row['station'].strip()}
    if len(stations)>1: raise DomainError('STATE','一次补读只能属于同一站点')
    return {'input_count':parsed['input_count'],'blank_count':parsed['blank_count'],
            'encoding':parsed['encoding'],'width_quarantine':parsed['quarantine'],
            'rows':parsed['raw'],'station':next(iter(stations),''),
            'digest':content_key(parsed['raw'])}

def validate(row,max_hours):
    if not row.get('station'): raise DomainError('MISSING','站点号缺失')
    src=source(row.get('source'))
    if src is None: raise DomainError('UNIT','读数来源必须为主表或后备表')
    if row.get('kind','station')!='station': raise DomainError('STATE','补读只接受总表读数')
    payload={**row,'bill':row.get('bill') or '0','order':row.get('order',''),'kind':'station'}
    parsed=normalize(payload,max_hours)
    return {'id':parsed['id'],'station':parsed['station'],'order':'','start':parsed['start'],
            'end':parsed['end'],'energy':parsed['energy'],'bill':parsed['bill'],
            'version':parsed['version'],'kind':'station','source':src,
            'line':row.get('_line','')}

def from_base(row):
    """An original batch's own station reading, kept for comparison only."""
    return {'id':row['id'],'station':row['station'],'order':'','start':instant(row['start']),
            'end':instant(row['end']),'energy':D(str(row['energy'])),'bill':D(str(row.get('bill',0))),
            'version':int(row.get('version',1)),'kind':'station','source':'原表',
            'line':row.get('_line','')}

def local_date(value):
    return instant(value).astimezone(ZONE).date().isoformat()

def split_periods(reading):
    """Cut a reading at local midnight so each local day can be confirmed alone."""
    cursor=reading['start'];end=reading['end']
    if end<=cursor: raise DomainError('RANGE','计量区间无效')
    total=D(str((end-cursor).total_seconds()));parts=[]
    while cursor<end:
        local=cursor.astimezone(ZONE)
        stop=min(end,datetime.combine(local.date(),time.min,ZONE)+timedelta(days=1))
        parts.append({**reading,'start':cursor,'end':stop,
                      'energy':reading['energy']*D(str((stop-cursor).total_seconds()))/total,
                      'period':local.date().isoformat()})
        cursor=stop
    parts[-1]['energy']+=reading['energy']-sum((p['energy'] for p in parts),D(0))
    return parts

def _seconds(start,end): return D(str((end-start).total_seconds()))

def free_windows(start,end,claimed):
    free=[(start,end)]
    for a,b in claimed:
        nxt=[]
        for s,e in free:
            if b<=s or a>=e: nxt.append((s,e));continue
            if s<a: nxt.append((s,min(a,e)))
            if e>b: nxt.append((max(b,s),e))
        free=nxt
    return sorted(x for x in free if x[0]<x[1])

def merge(readings):
    """Merge main-table and backup-table readings on one time axis.

    Main-table readings are claimed first; within one source, earlier readings
    claim first. Any later portion already covered is isolated (never dropped
    silently and never counted twice), so head-to-tail readings join seamlessly
    while small overlaps become explicit overlap records."""
    ordered=sorted(readings,key=lambda r:(PRIORITY.get(r['source'],2),r['start'],r['end'],r['id']))
    claimed=[];segments=[];isolated=[]
    for row in ordered:
        total=_seconds(row['start'],row['end'])
        free=free_windows(row['start'],row['end'],claimed)
        parts=[(a,b,row['energy']*_seconds(a,b)/total) for a,b in free]
        residual=row['energy']-sum((kwh for _,_,kwh in parts),D(0))
        for index,(a,b,kwh) in enumerate(parts,1):
            segments.append({'id':f"{row['id']}#{index}",'origin_id':row['id'],'station':row['station'],
                             'order':'','start':a,'end':b,'energy':kwh,'unit':'kWh','bill':D(0),
                             'version':row['version'],'kind':'station','source':row['source'],
                             'line':row['line']})
            claimed.append((a,b))
        if residual!=0:
            covered=free_windows(row['start'],row['end'],free)
            isolated.append({'line':row['line'],'key':row['id'],'code':'OVERLAP','reason':'有效区间重叠',
                             'detail':f"{row['source']} {row['id']} 与已采信读数重叠，按时长比例隔离 {residual} kWh",
                             'origin_id':row['id'],'source':row['source'],'energy':residual,
                             'start':row['start'],'end':row['end'],
                             'windows':[[a.isoformat(),b.isoformat()] for a,b in covered],
                             'raw':{'id':row['id'],'station':row['station'],'source':row['source'],
                                    'energy':str(row['energy'])}})
    return segments,isolated

def overlaps(segments):
    ordered=sorted(segments,key=lambda s:(s['start'],s['end']))
    return any(right['start']<left['end'] for left,right in zip(ordered,ordered[1:]))

def uncovered(start,end,segments):
    """Windows of [start,end) that the merged ledger does not cover."""
    return free_windows(start,end,[(s['start'],s['end']) for s in segments])
