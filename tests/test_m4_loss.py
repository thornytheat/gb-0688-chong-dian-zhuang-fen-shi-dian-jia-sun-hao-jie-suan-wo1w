import pytest
from decimal import Decimal as D
from app.errors import DomainError
from app.pipeline import run
from app.normalize import instant
from app.modules.m4_loss.rules import allocate
def rec(id,kind,energy):return dict(id=id,station='S',kind=kind,energy=D(energy),start=instant('2026-11-16T00:00:00Z'),end=instant('2026-11-17T00:00:00Z'))

def test_loss_proportion():
    x,b=allocate([rec('1','order','10'),rec('2','order','20'),rec('3','station','33')]);assert [r['loss_kwh'] for r in x]==[1,2] and b[0]['loss_kwh']==3

def test_negative_loss_blocked():
    x,b=allocate([rec('1','order','10'),rec('2','station','9')]);assert x[0]['loss_kwh']==0 and b[0]['state']!='通过'

def test_no_meter():
    assert allocate([rec('1','order','10')])[1][0]['state']!='通过'

def test_zero_orders():
    assert allocate([rec('1','station','10')])[1][0]['state']=='无订单承接损耗'

def test_real_three_stations(raw):
    assert len(run(raw,stop=4,persist=False)['loss_balances'])==3

def test_real_loss_conserved(raw):
    x=run(raw,stop=4,persist=False);assert sum(D(r['loss_kwh']) for r in x['orders'])==sum(D(r['loss_kwh']) for r in x['loss_balances'])

def test_clean_sample_has_covered_station_meters():
    from app.config import SAMPLES
    result=run((SAMPLES/'clean.csv').read_bytes(),stop=4,persist=False)
    assert result['input_count']==43 and not result['quarantine']
    assert len(result['loss_balances'])==3
    assert all(r['state']=='通过' for r in result['loss_balances'])


def test_meter_must_cover_order_interval():
    order=rec('1','order','10');meter=rec('2','station','11')
    meter['end']=instant('2026-11-16T12:00:00Z')
    assigned,balances=allocate([order,meter])
    assert balances[0]['state']=='总表未覆盖订单区间'
    assert assigned[0]['loss_kwh']==0
