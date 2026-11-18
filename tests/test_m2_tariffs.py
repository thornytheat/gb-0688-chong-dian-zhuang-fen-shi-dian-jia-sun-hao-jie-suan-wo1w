import pytest
from decimal import Decimal as D
from app.errors import DomainError
from app.pipeline import run
from app.normalize import instant
from app.modules.m2_tariffs.rules import tariffs,normalize,dedup,DEFAULT_TARIFFS
def row(**kw):
 x=dict(id='1',station='S1',order='01',start='2026-11-16T16:30:00+08:00',end='2026-11-16T17:30:00+08:00',energy='1,000',unit='kWh',bill='1',version='1',kind='order',_line=2);x.update(kw);return x

def test_fullwidth_energy():
    # TRAP-06
    assert normalize(row(energy='１，０００'),D(72))['energy']==1000

def test_sentinel():
    # TRAP-07
    with pytest.raises(DomainError):normalize(row(energy='N/A'),D(72))

def test_mixed_units():
    # TRAP-15
    assert normalize(row(energy='1',unit='MWh'),D(72))['energy']==1000

def test_overlap_versions():
    # TRAP-25
    with pytest.raises(DomainError):tariffs(DEFAULT_TARIFFS+[DEFAULT_TARIFFS[0]])

def test_real_versions(raw):
    assert len(run(raw,stop=2,persist=False)['tariffs'])==2

def test_real_conflict(raw):
    # TRAP-14
    assert sum(x['code']=='CONFLICT' for x in run(raw,stop=2,persist=False)['quarantine'])==2

def test_real_unit(raw):
    assert all(x['unit']=='kWh' for x in run(raw,stop=2,persist=False)['records'])

