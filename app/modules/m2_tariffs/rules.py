from app.normalize import number,instant
from app.errors import DomainError
from datetime import date
from collections import defaultdict
from app.reasons import rejected
from decimal import Decimal as D
DEFAULT_TARIFFS=[{'from':'2026-01-01','to':'2026-11-17','hours':[[0,7,'.35'],[7,17,'.75'],[17,22,'1.10'],[22,24,'.75']]},{'from':'2026-11-17','to':'2027-01-01','hours':[[0,7,'.35'],[7,17,'.75'],[17,22,'1.20'],[22,24,'.75']]}]
def tariffs(items):
    if not isinstance(items,list) or not items:raise DomainError('TARIFF','费率版本不可为空')
    result=[]
    try:
        for item in items:
            start=date.fromisoformat(item['from']);end=date.fromisoformat(item['to'])
            if start>=end:raise DomainError('RANGE','费率日期倒置')
            hours=sorted([(int(a),int(b),number(c)) for a,b,c in item['hours']]);cursor=0
            for a,b,rate in hours:
                if a!=cursor or not a<b<=24 or rate<0:raise DomainError('OVERLAP','日费率必须连续覆盖24小时')
                cursor=b
            if cursor!=24:raise DomainError('TARIFF','日费率不完整')
            result.append({'from':start,'to':end,'hours':hours})
    except (KeyError,ValueError,TypeError):raise DomainError('TARIFF','费率格式错误')
    result.sort(key=lambda x:x['from'])
    for left,right in zip(result,result[1:]):
        if left['to']>right['from']:raise DomainError('OVERLAP','费率版本生效期重叠')
    return result
def normalize(row,max_hours):
    out=dict(row);out['start']=instant(row['start']);out['end']=instant(row['end'])
    if out['end']<=out['start'] or D(str((out['end']-out['start']).total_seconds()))>max_hours*3600:raise DomainError('RANGE','计量区间无效')
    if row['unit'] not in ('kWh','MWh'):raise DomainError('UNIT','电量单位无效')
    out['energy']=number(row['energy'])*(1000 if row['unit']=='MWh' else 1);out['unit']='kWh';out['bill']=number(row['bill']);v=number(row['version'])
    if out['energy']<0 or out['bill']<0 or v<1 or v!=v.to_integral():raise DomainError('RANGE','电量金额或版本无效')
    out['version']=int(v)
    if row['kind'] not in ('order','station'):raise DomainError('STATE','读数类型无效')
    if row['kind']=='order' and not row['order']:raise DomainError('MISSING','订单号缺失')
    return out
def dedup(rows):
    groups=defaultdict(list)
    for row in rows:groups[row['id']].append(row)
    good=[];bad=[]
    for key,group in sorted(groups.items()):
        latest=max(r['version'] for r in group);candidates=[r for r in group if r['version']==latest]
        sig=lambda r:tuple(str(r[k]) for k in ['station','order','start','end','energy','bill','kind'])
        if len({sig(r) for r in candidates})>1:bad.extend(rejected(r,'CONFLICT','同版计量冲突') for r in group);continue
        chosen=min(candidates,key=lambda r:r['_line']);good.append(chosen);bad.extend(rejected(r,'DUPLICATE','重复或旧版') for r in group if r is not chosen)
    return good,bad
