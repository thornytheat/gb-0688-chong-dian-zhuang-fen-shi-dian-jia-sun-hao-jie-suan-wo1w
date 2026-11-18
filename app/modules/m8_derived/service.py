from datetime import datetime,timezone
from decimal import Decimal as D
from app.errors import DomainError
from app.reasons import rejected
from app.normalize import number,serial
from app import store
from .rules import (DERIVE_VERSION,parse,validate,from_base,split_periods,merge,
                    uncovered,overlaps,key_for,local_date,free_windows)
from app.normalize import instant

def _serial(rows):
    out=[]
    for row in rows:
        item=dict(row)
        for field in ('start','end'):
            if hasattr(item.get(field),'isoformat'): item[field]=item[field].isoformat()
        for field in ('energy','kwh','bill','rate','fee','loss_kwh','amount','delta'):
            if field in item: item[field]=str(item[field])
        if 'windows' in item: item['windows']=[[a,b] for a,b in item['windows']]
        if 'raw' in item: item['raw']={k:v for k,v in item['raw'].items()}
        out.append(item)
    return out

def _revive(rows):
    return [{**row,'start':datetime.fromisoformat(row['start']),
             'end':datetime.fromisoformat(row['end']),
             'energy':D(str(row['energy'])),'bill':D(str(row['bill']))} for row in rows]

def _base(record):
    base=store.fetch(record['parent'])
    if not isinstance(base,dict) or 'records' not in base: raise DomainError('STATE','原批次不可用')
    return base

def _validate(rows,max_hours):
    readings=[];quarantine=[]
    for row in rows:
        try: readings.extend(split_periods(validate(row,max_hours)))
        except DomainError as exc: quarantine.append(rejected(row,exc.code,exc.message))
    return readings,quarantine

def preview(record,raw,max_hours):
    parsed=parse(raw)
    if parsed['station'] and parsed['station']!=record['station']:
        raise DomainError('STATE','补读站点与版本站点不一致')
    readings,quarantine=_validate(parsed['rows'],max_hours)
    return {'station':record['station'],'parent':record['parent'],'digest':parsed['digest'],
            'encoding':parsed['encoding'],'input_count':parsed['input_count'],
            'blank_count':parsed['blank_count'],
            'periods':sorted({r['period'] for r in readings}),
            'readings':_serial(readings),'quarantine':[*parsed['width_quarantine'],*quarantine],
            'max_hours':str(max_hours)}

def confirm_periods(derived_id,play,resume=True):
    """Confirm the merge one local day at a time. Each confirmed period is written
    before the next starts, so an interrupted run resumes exactly there."""
    confirmed=dict(play.get('confirmed') or {})
    readings=_revive(play['readings'])
    for period in play['periods']:
        if resume and period in confirmed: continue
        subset=[r for r in readings if local_date(r['start'])<=period]
        segments,isolated=merge(subset)
        problems=_balance(subset,segments,isolated)
        if problems:
            play['confirmed']=confirmed
            raise DomainError(problems[0][0],problems[0][1])
        confirmed[period]={'segments':len(segments),'isolated':len(isolated),
                           'accepted_kwh':str(sum((x['energy'] for x in segments),D(0))),
                           'at':datetime.now(timezone.utc).isoformat()}
        play['confirmed']=confirmed
        store.derived_progress(derived_id,play)
    return play

def _balance(readings,segments,isolated,kept=D(0)):
    """All accepted backfill kWh must land in the merged ledger: accepted plus
    isolated must equal what was read, and the kept original share only adds to
    the ledger, never to the backfill's own totals."""
    problems=[]
    if overlaps(segments): problems.append(('OVERLAP','合并后仍存在重叠时段'))
    accepted=sum((x['energy'] for x in segments),D(0))
    expected=sum((x['energy'] for x in readings),D(0))-sum((x['energy'] for x in isolated),D(0))
    if accepted!=expected: problems.append(('INCOMPLETE',f'补读电量不守恒 采信{accepted} 应为{expected}'))
    return problems

def ledger(play,base):
    """Build the station's new meter ledger from the backfill plus the part of the
    original reading the backfill does not replace. Conservation is checked over
    the backfill alone; the kept original share is reported separately."""
    readings=_revive(play['readings'])
    segments,isolated=merge(readings)
    original=[from_base(r) for r in base['records']
              if r.get('kind')=='station' and r.get('station')==play['station']]
    kept=D(0);residual=[]
    for row in original:
        total=D(str((row['end']-row['start']).total_seconds()))
        for index,(a,b) in enumerate(uncovered(row['start'],row['end'],segments),1):
            share=row['energy']*D(str((b-a).total_seconds()))/total
            kept+=share
            residual.append({**row,'id':f"{row['id']}~{index}",'origin_id':row['id'],
                             'start':a,'end':b,'energy':share,'source':'原表'})
    rows=segments+residual
    problems=_balance(readings,segments,isolated)
    if problems: raise DomainError(problems[0][0],problems[0][1])
    return rows,isolated,original,kept

def build(ctx):
    """Derive a related version from an original batch without touching it."""
    parent=ctx.get('parent')
    if not parent: raise DomainError('STATE','请提供原批次')
    base=store.fetch(parent)
    if not isinstance(base,dict) or 'records' not in base: raise DomainError('STATE','原批次不可用')
    parsed=parse(ctx['source'])
    if not parsed['station']: raise DomainError('STATE','补读缺少站点')
    derived_id=key_for(parent,parsed['digest'],parsed['station'])[:20]
    record=store.derived_claim(derived_id,parent,parsed['station'],
                               key_for(parent,parsed['digest'],parsed['station']))
    if record['payload']: return render(record,reused=True)
    play=preview(record,ctx['source'],number(ctx['params']['max_hours']))
    if not play['readings']:
        store.derived_status(derived_id,'核对失败')
        reason=play['quarantine'][0]['code'] if play['quarantine'] else 'INCOMPLETE'
        detail=play['quarantine'][0].get('detail') if play['quarantine'] else '补读没有可采信读数'
        raise DomainError(reason,f'补读没有可采信读数：{detail}')
    play['confirmed']=dict(record['progress'].get('confirmed') or {})
    try:
        confirm_periods(derived_id,play)
        rows,isolated,original,kept=ledger(play,base)
        original_total=sum((r['energy'] for r in original),D(0))
        payload={'station':play['station'],'parent':parent,'digest':play['digest'],
                 'rules':DERIVE_VERSION,'periods':play['periods'],
                 'readings':_serial(_revive(play['readings'])),
                 'original':_serial(original),
                 'segments':_serial(rows),'isolated':_serial(isolated),
                 'quarantine':play['quarantine']}
        basis={'parent':parent,'digest':play['digest'],'station':play['station'],
               'rules':DERIVE_VERSION,'periods':play['periods'],
               'confirmed':play['confirmed'],'input_count':play['input_count'],
               'encoding':play['encoding'],
               'sources':{src:sum(1 for r in payload['readings'] if r['source']==src)
                          for src in ('主表','后备表')},
               'original_kept_kwh':str(kept),
               'original_replaced_kwh':str(original_total-kept),
               'accepted_kwh':str(sum((x['energy'] for x in rows),D(0))),
               'isolated_kwh':str(sum((D(str(x['energy'])) for x in isolated),D(0))),
               'isolated':_serial(isolated),'quarantine':play['quarantine']}
        store.derived_result(derived_id,payload,basis,'待核对')
    except Exception as exc:
        # A failed or interrupted run leaves the version retryable; confirmed
        # periods stay in progress so the next attempt resumes from them.
        if isinstance(exc,DomainError): store.derived_status(derived_id,'核对失败')
        raise
    return render(store.derived_get(derived_id),reused=False)

def _orders(base,station):
    """All order rows plus the other stations' untouched meter readings."""
    out=[]
    for row in base['records']:
        if row['kind']=='order' or (row['kind']=='station' and row.get('station')!=station):
            out.append({**row,'start':datetime.fromisoformat(row['start']),
                        'end':datetime.fromisoformat(row['end']),
                        'energy':D(str(row['energy'])),'bill':D(str(row['bill'])),
                        'version':int(row['version'])})
    return out

def _scope_problems(base,station,segments):
    """A backfill may only extend the settlement window where orders exist. A
    window outside the original station coverage and outside every order interval
    would silently inflate station loss, so it blocks the switch."""
    original=[from_base(r) for r in base['records']
              if r.get('kind')=='station' and r.get('station')==station]
    orders=[r for r in base['records'] if r.get('kind')=='order' and r.get('station')==station]
    if not original: return []
    allowed=[(r['start'],r['end']) for r in original]+[(instant(r['start']),instant(r['end'])) for r in orders]
    problems=[]
    for row in segments:
        outside=free_windows(instant(row['start']),instant(row['end']),allowed)
        if outside:
            problems.append(('RANGE',f"补读 {row.get('origin_id',row['id'])} 超出原结算区间且无订单支撑"))
            break
    return problems

def reconcile(ctx):
    """Re-run accounting on the derived ledger and decide whether it may switch."""
    from app.modules.m2_tariffs.rules import tariffs,DEFAULT_TARIFFS
    from app.modules.m3_split.rules import split
    from app.modules.m4_loss.rules import allocate
    from app.modules.m5_fees.rules import charges
    from app.modules.m6_bills.rules import compare
    record=store.derived_get(ctx['derived_id'])
    if record is None: raise DomainError('NOT_FOUND','派生版本不存在',404)
    if not record['payload']: raise DomainError('STATE','派生版本尚未生成')
    params=ctx['params'];base=_base(record);station=record['station']
    records=_orders(base,station)+_revive(record['payload']['segments'])
    rates=tariffs(params.get('tariffs') or base.get('tariffs') or DEFAULT_TARIFFS)
    segs=[]
    for row in records:
        if row['kind']!='order': continue
        segs.extend(split(row,rates))
    assigned,balances=allocate(records)
    fees=charges(assigned,segs,number(params['loss_rate']))
    bills=compare(fees,number(params['bill_tolerance']))
    original={b['station']:b for b in base['loss_balances']}
    balance=next((b for b in balances if b['station']==station),None)
    problems=[]
    if balance is None: problems.append(('STATE','派生版本没有覆盖该站点'))
    elif balance['state']!='通过': problems.append(('STATE',f"站点损耗判定未通过：{balance['state']}"))
    elif D(str(balance['loss_kwh']))<0: problems.append(('NEGATIVE','损耗为负'))
    for item in balances:
        if item['station']==station: continue
        before=original.get(item['station'],{}).get('loss_kwh')
        if before is None or D(str(before))!=D(str(item['loss_kwh'])):
            problems.append(('STATE',f"合并影响了 {item['station']} 的损耗"))
    if overlaps(_revive(record['payload']['segments'])):
        problems.append(('OVERLAP','合并后仍存在重叠时段'))
    problems.extend(_scope_problems(base,station,_revive(record['payload']['segments'])))
    summary={'station':station,'accepted_kwh':record['basis'].get('accepted_kwh'),
             'isolated_kwh':record['basis'].get('isolated_kwh'),
             'loss_kwh':balance['loss_kwh'] if balance else None,
             'meter_kwh':balance['meter_kwh'] if balance else None,
             'order_kwh':balance['order_kwh'] if balance else None,
             'orders':len(assigned),'bills':len(bills),
             'amount':str(sum((x['amount'] for x in fees),D(0))),
             'isolated_rows':len(record['payload']['isolated'])}
    result={'station':station,'segments':_serial(segs),'loss_balances':balances,
            'orders':assigned,'charges':fees,'bills':bills,'audit':summary,'problems':problems}
    status='已核对' if not problems else '核对失败'
    if record['status']=='当前': status='当前'
    elif record['status']=='已替换': status='已替换'
    store.derived_result(record['id'],serial({**record['payload'],'result':result}),serial(record['basis']),status)
    return serial(result)

def activate(ctx):
    """Switch the station's single current ledger, restoring the old bill if the
    new one cannot be written. The original batch is never modified."""
    record=store.derived_get(ctx['derived_id'])
    if record is None: raise DomainError('NOT_FOUND','派生版本不存在',404)
    if record['status']=='当前':
        return {'station':record['station'],'current':store.current_for(record['station']),
                'derived_id':record['id'],'original':record['parent']}
    if record['status']!='已核对': raise DomainError('STATE','请先核对通过再切换当前账')
    base=_base(record)
    store.seed_current(record['station'],base['manifest']['run_id'])
    current=store.activate(record['id'],journal=ctx.get('journal'))
    return {'station':record['station'],'current':current,'derived_id':record['id'],
            'original':base['manifest']['run_id']}

def render(record,reused=False):
    base=store.fetch(record['parent'])
    current=store.current_for(record['station']) or {'ledger_id':None,'ledger_kind':None}
    return {'derived_id':record['id'],'key':record['key'],'parent':record['parent'],
            'station':record['station'],'status':record['status'],'basis':record['basis'],
            'progress':record['progress'],'payload':record['payload'],'reused':reused,
            'current':current,'history':store.switch_history(record['station'],20),
            'original':{'run_id':base['manifest']['run_id'],'review':base.get('review'),
                        'version':base.get('version'),'loss_balances':base.get('loss_balances'),
                        'bills':base.get('bills'),'audit':base.get('audit'),
                        'quarantine':base.get('quarantine')}}
