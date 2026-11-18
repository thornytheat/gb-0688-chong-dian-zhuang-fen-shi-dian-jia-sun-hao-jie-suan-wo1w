import pytest
from decimal import Decimal as D
from app.errors import DomainError
from app.pipeline import run
from app.normalize import instant
from app.modules.m1_intake.rules import receive
from app.config import SAMPLES

def test_real_bom(raw):
    assert receive(raw)['records'][0]['id']=='00001'

def test_real_input_count(raw):
    assert receive(raw)['input_count']==49

def test_real_width_isolated(raw):
    assert any(x['code']=='COLUMN_COUNT' for x in receive(raw)['quarantine'])

def test_empty():
    with pytest.raises(DomainError):receive(b'')

def test_wrong_header():
    with pytest.raises(DomainError):receive(b'a,b\n1,2')

def test_legacy():
    assert receive((SAMPLES/'legacy.csv').read_bytes())['encoding']=='gb18030'

def test_key_string(raw):
    assert isinstance(receive(raw)['records'][0]['order'],str)

