import pytest
from decimal import Decimal as D
from app.errors import DomainError
from app.pipeline import run
from app.normalize import instant
from app.modules.m7_batches.rules import summary

def test_row_mismatch():
    with pytest.raises(DomainError):summary([],[],1,[],[],[])

def test_energy_mismatch():
    with pytest.raises(DomainError):summary([{'kind':'order','energy':D(1)}],[],1,[],[],[])

def test_empty():
    assert summary([],[],0,[],[],[])['amount']==0

def test_blocked_summary():
    assert summary([],[],0,[],[{'state':'缺表'}],[])['blocked_stations']==1

def test_real_four_ledger(raw):
    x=run(raw,persist=False);assert x['audit']['input']==x['audit']['retained']+x['audit']['isolated']

def test_real_energy(raw):
    x=run(raw,persist=False);assert D(x['audit']['measured_kwh'])==D(x['audit']['split_kwh'])

def test_real_idempotent(raw,isolate):
    assert run(raw)['manifest']['run_id']==run(raw)['manifest']['run_id']

