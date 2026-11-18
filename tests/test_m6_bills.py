import pytest
from decimal import Decimal as D
from app.errors import DomainError
from app.pipeline import run
from app.normalize import instant
from app.modules.m6_bills.rules import compare
def r(amount,bill,state='通过'):return dict(amount=D(amount),bill=D(bill),loss_state=state)

def test_exact_bill():
    assert compare([r('1','1')],D('.01'))[0]['state']=='通过'

def test_tolerance_boundary():
    assert compare([r('1.01','1')],D('.01'))[0]['state']=='通过'

def test_large_difference():
    assert compare([r('2','1')],D('.01'))[0]['delta']==1

def test_blocked_station():
    assert compare([r('1','1','总表缺失')],D('.01'))[0]['state']=='待复核'

def test_real_differences(raw):
    assert any(r['state']=='待复核' for r in run(raw,stop=6,persist=False)['bills'])

def test_real_delta_sum(raw):
    x=run(raw,stop=6,persist=False)['bills'];assert sum(D(r['delta']) for r in x)==sum(D(r['amount'])-D(r['bill']) for r in x)

def test_real_orders(raw):
    assert len(run(raw,stop=6,persist=False)['bills'])==40

