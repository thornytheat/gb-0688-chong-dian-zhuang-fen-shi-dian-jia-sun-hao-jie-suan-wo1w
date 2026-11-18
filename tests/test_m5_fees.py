import pytest
from decimal import Decimal as D
from app.errors import DomainError
from app.pipeline import run
from app.normalize import instant
from app.modules.m5_fees.rules import charges
def o(id):return dict(id=id,station='S',loss_kwh=D(0),loss_state='通过')

def test_pennies_conserved():
    # TRAP-24
    x=charges([o('1'),o('2'),o('3')],[{'id':str(i),'fee':D('.005')} for i in range(1,4)],D(0));assert sum(r['amount'] for r in x)==D('.02')

def test_decimal_exact():
    # TRAP-10
    x=charges([o('1')],[{'id':'1','fee':D('.1')} for _ in range(1000)],D(0));assert x[0]['amount']==100

def test_loss_fee():
    x=o('1');x['loss_kwh']=D(2);assert charges([x],[],D('.65'))[0]['amount']==D('1.30')

def test_empty():
    assert charges([],[],D(1))==[]

def test_real_currency_scale(raw):
    assert all(D(x['amount']).as_tuple().exponent==-2 for x in run(raw,stop=5,persist=False)['charges'])

def test_real_count(raw):
    assert len(run(raw,stop=5,persist=False)['charges'])==40

def test_real_positive_fee(raw):
    assert all(D(x['amount'])>0 for x in run(raw,stop=5,persist=False)['charges'])

