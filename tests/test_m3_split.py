import pytest
from decimal import Decimal as D
from app.errors import DomainError
from app.pipeline import run
from app.normalize import instant
from app.modules.m3_split.rules import split
from app.modules.m2_tariffs.rules import tariffs,DEFAULT_TARIFFS
def row(start='2026-11-16T16:30:00+08:00',end='2026-11-16T17:30:00+08:00',energy='10'):
 return dict(id='1',station='S1',order='01',start=instant(start),end=instant(end),energy=D(energy))
R=tariffs(DEFAULT_TARIFFS)

def test_boundary_split():
    # TRAP-23
    x=split(row(),R);assert [p['kwh'] for p in x]==[D(5),D(5)] and sum(p['fee'] for p in x)==D('9.25')

def test_timezone_equivalent():
    # TRAP-11
    assert split(row('2026-11-16T08:30:00Z','2026-11-16T09:30:00Z'),R)==split(row(),R)

def test_midnight_version():
    x=split(row('2026-11-16T23:00:00+08:00','2026-11-17T01:00:00+08:00'),R);assert [p['rate'] for p in x]==[D('.75'),D('.35')]

def test_missing_rate():
    with pytest.raises(DomainError):split(row('2028-01-01T00:00:00Z','2028-01-01T01:00:00Z'),R)

def test_real_kwh_conserved(raw):
    x=run(raw,stop=3,persist=False);assert sum(D(p['kwh']) for p in x['segments'])==sum(D(p['energy']) for p in x['records'] if p['kind']=='order')

def test_real_segments(raw):
    assert len(run(raw,stop=3,persist=False)['segments'])>40

def test_real_positive_parts(raw):
    assert all(D(p['kwh'])>=0 for p in run(raw,stop=3,persist=False)['segments'])

