from datetime import datetime,timedelta,timezone
from decimal import Decimal as D
from app.errors import DomainError
ZONE=timezone(timedelta(hours=8))
def split(row,rates):
    cursor=row['start'];end=row['end'];seconds=D(str((end-cursor).total_seconds()));result=[]
    while cursor<end:
        local=cursor.astimezone(ZONE);version=next((v for v in rates if v['from']<=local.date()<v['to']),None)
        if version is None:raise DomainError('TARIFF','时段没有生效费率')
        slot=next((p for p in version['hours'] if p[0]<=local.hour<p[1]),None)
        if slot is None:raise DomainError('TARIFF','时段未覆盖')
        a,b,rate=slot
        boundary=datetime.combine(local.date(),datetime.min.time(),ZONE)+timedelta(hours=b)
        stop=min(end,boundary);fraction=D(str((stop-cursor).total_seconds()))/seconds
        kwh=row['energy']*fraction
        result.append({'id':row['id'],'station':row['station'],'order':row['order'],'start':cursor,'end':stop,'kwh':kwh,'rate':rate,'fee':kwh*rate})
        cursor=stop
    # Keep measured energy exact after non-terminating Decimal divisions.
    if result:
        result[-1]['kwh']+=row['energy']-sum((p['kwh'] for p in result),D(0));result[-1]['fee']=result[-1]['kwh']*result[-1]['rate']
    return result
