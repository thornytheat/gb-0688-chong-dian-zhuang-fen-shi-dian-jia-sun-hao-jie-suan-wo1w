from app.errors import DomainError
from decimal import Decimal as D
def summary(records,bad,total,segments,balances,charges):
    if len(records)+len(bad)!=total:raise DomainError('INCOMPLETE','计量行数不守恒')
    measured=sum((r['energy'] for r in records if r['kind']=='order'),D(0));split=sum((r['kwh'] for r in segments),D(0))
    if measured!=split:raise DomainError('INCOMPLETE','分时电量不守恒')
    return {'input':total,'retained':len(records),'isolated':len(bad),'measured_kwh':measured,'split_kwh':split,'amount':sum((r['amount'] for r in charges),D(0)),'blocked_stations':sum(r['state']!='通过' for r in balances)}
