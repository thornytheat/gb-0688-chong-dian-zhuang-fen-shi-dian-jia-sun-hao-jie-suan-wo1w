import pytest
from decimal import Decimal as D
from datetime import datetime,timezone
from app.config import SAMPLES
from app.errors import DomainError
from app.pipeline import run
from app import store
from app.modules.m8_derived import service
from app.modules.m8_derived.rules import merge,validate,content_key

BASE_TEXT=(SAMPLES/'backfill.csv').read_text(encoding='utf-8-sig')
HEADER="id,station,start,end,energy,unit,version,source\n"

def reading(id,start,end,energy,source='后备表',station='站甲'):
    return {'id':id,'station':station,'start':start,'end':end,'energy':D(energy),
            'unit':'kWh','version':1,'kind':'station','source':source,'bill':D(0),'line':2}

def utc(text): return datetime.fromisoformat(text)

@pytest.fixture
def base(raw,isolate):
    return run(raw)

@pytest.fixture
def derived(base):
    return service.build({'source':BASE_TEXT.encode(),'params':base['params'],
                          'parent':base['manifest']['run_id']})

def test_head_to_tail_merge_is_seamless():
    rows=[reading('A','2026-11-16T00:00:00+08:00','2026-11-16T12:00:00+08:00','10'),
          reading('B','2026-11-16T12:00:00+08:00','2026-11-17T00:00:00+08:00','11')]
    for row in rows: row['start']=utc(row['start']);row['end']=utc(row['end'])
    segments,isolated=merge(rows)
    assert isolated==[]
    assert [s['energy'] for s in segments]==[D(10),D(11)]
    assert sum(D(s['energy']) for s in segments)==D(21)

def test_overlap_is_isolated_not_double_counted():
    rows=[reading('A','2026-11-16T00:00:00+08:00','2026-11-16T12:00:00+08:00','12'),
          reading('B','2026-11-16T10:00:00+08:00','2026-11-16T20:00:00+08:00','10')]
    for row in rows: row['start']=utc(row['start']);row['end']=utc(row['end'])
    segments,isolated=merge(rows)
    assert len(isolated)==1 and isolated[0]['code']=='OVERLAP'
    assert isolated[0]['energy']==D(2)
    assert sum(D(s['energy']) for s in segments)==D(20)

def test_main_table_wins_over_backup():
    rows=[reading('A','2026-11-16T00:00:00+08:00','2026-11-16T12:00:00+08:00','12','主表'),
          reading('B','2026-11-16T00:00:00+08:00','2026-11-16T12:00:00+08:00','9','后备表')]
    for row in rows: row['start']=utc(row['start']);row['end']=utc(row['end'])
    segments,isolated=merge(rows)
    assert [s['source'] for s in segments]==['主表']
    assert isolated[0]['source']=='后备表' and isolated[0]['energy']==D(9)

def test_bad_source_rejected():
    with pytest.raises(DomainError): validate({'id':'X','station':'站甲','start':'2026-11-16T00:00:00+08:00','end':'2026-11-16T01:00:00+08:00','energy':'1','unit':'kWh','version':'1','kind':'station','source':'影子表','_line':2},D(72))

def test_order_rows_rejected():
    with pytest.raises(DomainError): validate({'id':'X','station':'站甲','start':'2026-11-16T00:00:00+08:00','end':'2026-11-16T01:00:00+08:00','energy':'1','unit':'kWh','version':'1','kind':'order','source':'主表','_line':2},D(72))

def test_build_isolates_overlap_and_keeps_original(base,derived):
    assert derived['status']=='待核对'
    assert derived['parent']==base['manifest']['run_id']
    assert D(derived['basis']['isolated_kwh'])>0
    # original batch is untouched
    again=store.fetch(base['manifest']['run_id'])
    assert again['loss_balances']==base['loss_balances']
    assert again['audit']==base['audit']

def test_original_ledger_unaffected_by_derivation(base,derived):
    assert store.fetch(derived['parent'])['bills']==base['bills']

def test_duplicate_backfill_reuses_version(base,derived):
    again=service.build({'source':BASE_TEXT.encode(),'params':base['params'],
                         'parent':base['manifest']['run_id']})
    assert again['reused'] is True
    assert again['derived_id']==derived['derived_id']
    assert len(store.derived_list())==1

def test_equivalent_spelling_reuses_version(base,derived):
    text=BASE_TEXT.replace('30,','30.0,').replace('35,','35.0,')
    shuffled=text.strip().splitlines()
    body="\n".join([shuffled[0]]+list(reversed(shuffled[1:])))
    again=service.build({'source':('﻿'+body).encode(),'params':base['params'],
                         'parent':base['manifest']['run_id']})
    assert again['derived_id']==derived['derived_id']

def test_different_content_is_a_new_version(base,derived):
    text=BASE_TEXT.replace(',30,',',31,')
    again=service.build({'source':text.encode(),'params':base['params'],
                         'parent':base['manifest']['run_id']})
    assert again['derived_id']!=derived['derived_id']
    assert len(store.derived_list())==2

def test_reconcile_passes_and_switches(base,derived):
    result=service.reconcile({'derived_id':derived['derived_id'],'params':base['params']})
    assert result['problems']==[]
    balance=next(b for b in result['loss_balances'] if b['station']=='站甲')
    assert balance['state']=='通过'
    assert store.derived_get(derived['derived_id'])['status']=='已核对'
    service.activate({'derived_id':derived['derived_id']})
    current=store.current_for('站甲')
    assert current['ledger_id']==derived['derived_id'] and current['ledger_kind']=='derived'
    assert store.derived_get(derived['derived_id'])['status']=='当前'

def test_activate_is_idempotent(base,derived):
    service.reconcile({'derived_id':derived['derived_id'],'params':base['params']})
    first=service.activate({'derived_id':derived['derived_id']})
    second=service.activate({'derived_id':derived['derived_id']})
    assert first['current']==second['current']
    assert len(store.switch_history('站甲'))==1

def test_activate_requires_check(base,derived):
    with pytest.raises(DomainError) as exc: service.activate({'derived_id':derived['derived_id']})
    assert exc.value.code=='STATE'

def test_failed_write_restores_old_bill(base,derived):
    service.reconcile({'derived_id':derived['derived_id'],'params':base['params']})
    def boom(db): raise RuntimeError('disk full')
    with pytest.raises(DomainError) as exc:
        service.activate({'derived_id':derived['derived_id'],'journal':boom})
    assert exc.value.code=='WRITE'
    current=store.current_for('站甲')
    assert current['ledger_id']==base['manifest']['run_id'] and current['ledger_kind']=='run'
    assert store.derived_get(derived['derived_id'])['status']!='当前'
    assert any('恢复旧版账单' in row['reason'] for row in store.switch_history('站甲'))

def test_restore_previous_ledger(base,derived):
    service.reconcile({'derived_id':derived['derived_id'],'params':base['params']})
    service.activate({'derived_id':derived['derived_id']})
    restored=store.restore('站甲')
    assert restored['ledger_id']==base['manifest']['run_id']
    assert store.fetch(base['manifest']['run_id'])['review']==base['review']

def test_interrupted_run_resumes(base,derived,monkeypatch):
    store.derived_list()
    key='resume-test'
    normal=store.derived_progress
    calls=[]
    def interrupt(derived_id,progress):
        calls.append(derived_id)
        if len(calls)==2: raise RuntimeError('interrupted')
        return normal(derived_id,progress)
    monkeypatch.setattr(store,'derived_progress',interrupt)
    text=BASE_TEXT.replace(',30,',',29,')
    with pytest.raises(RuntimeError):
        service.build({'source':text.encode(),'params':base['params'],'parent':base['manifest']['run_id']})
    pending=[r for r in store.derived_list() if r['progress'].get('confirmed')]
    assert pending and len(pending[0]['progress']['confirmed'])==1
    monkeypatch.setattr(store,'derived_progress',normal)
    resumed=service.build({'source':text.encode(),'params':base['params'],'parent':base['manifest']['run_id']})
    assert resumed['status']=='待核对'
    assert len(store.derived_list())==2

def test_partial_backfill_keeps_original_share(base):
    text=HEADER+"B0001,站甲,2026-11-16T00:00:00+08:00,2026-11-16T08:00:00+08:00,30,kWh,1,主表\n"
    derived=service.build({'source':text.encode(),'params':base['params'],'parent':base['manifest']['run_id']})
    assert D(derived['basis']['original_kept_kwh'])>0
    sources={row['source'] for row in derived['payload']['segments']}
    assert sources=={'主表','原表'}
    result=service.reconcile({'derived_id':derived['derived_id'],'params':base['params']})
    assert result['problems']==[]

def test_scope_overflow_blocks_switch(base):
    text=HEADER+"B0001,站甲,2026-11-18T00:00:00+08:00,2026-11-19T00:00:00+08:00,50,kWh,1,后备表\n"
    derived=service.build({'source':text.encode(),'params':base['params'],'parent':base['manifest']['run_id']})
    result=service.reconcile({'derived_id':derived['derived_id'],'params':base['params']})
    assert any(code=='RANGE' for code,_ in result['problems'])
    assert store.derived_get(derived['derived_id'])['status']=='核对失败'
    with pytest.raises(DomainError): service.activate({'derived_id':derived['derived_id']})

def test_negative_loss_blocks_switch(base):
    text=HEADER+"B0001,站甲,2026-11-16T00:00:00+08:00,2026-11-18T00:00:00+08:00,100,kWh,1,后备表\n"
    derived=service.build({'source':text.encode(),'params':base['params'],'parent':base['manifest']['run_id']})
    result=service.reconcile({'derived_id':derived['derived_id'],'params':base['params']})
    assert any('损耗' in msg for _,msg in result['problems'])

def test_other_stations_untouched(base,derived):
    result=service.reconcile({'derived_id':derived['derived_id'],'params':base['params']})
    for station in ('站乙','站丙'):
        before=next(b for b in base['loss_balances'] if b['station']==station)
        after=next(b for b in result['loss_balances'] if b['station']==station)
        assert before['loss_kwh']==after['loss_kwh']

def test_unknown_station_is_rejected(base):
    text=HEADER+"B0001,站丁,2026-11-16T00:00:00+08:00,2026-11-17T00:00:00+08:00,10,kWh,1,后备表\n"
    derived=service.build({'source':text.encode(),'params':base['params'],'parent':base['manifest']['run_id']})
    result=service.reconcile({'derived_id':derived['derived_id'],'params':base['params']})
    assert result['problems']

def test_evidence_and_pages(client):
    base=client.post('/api/runs',json={}).json
    created=client.post('/api/m8',json={'parent':base['manifest']['run_id'],'text':BASE_TEXT})
    assert created.status_code==200
    did=created.json['derived_id']
    assert client.post(f'/api/m8/{did}/check',json={}).status_code==200
    assert client.post(f'/api/m8/{did}/activate',json={}).status_code==200
    assert client.get(f'/m/8?derived={did}').status_code==200
    evidence=client.get(f'/api/m8/{did}/evidence.csv')
    assert evidence.status_code==200
    assert '重叠隔离' in evidence.text and '原批次损耗' in evidence.text
    listing=client.get('/api/m8').json
    assert listing['currents'][0]['ledger_kind']=='derived'

def test_bad_source_over_http(client):
    base=client.post('/api/runs',json={}).json
    text=HEADER+"B0001,站甲,2026-11-16T00:00:00+08:00,2026-11-16T08:00:00+08:00,30,kWh,1,影子表\n"
    reply=client.post('/api/m8',json={'parent':base['manifest']['run_id'],'text':text})
    assert reply.status_code==422
    assert reply.json['code']=='UNIT'
