from .rules import tariffs,normalize,dedup,DEFAULT_TARIFFS
from app.normalize import number
from app.errors import DomainError
from app.reasons import rejected
def execute(ctx):
    rates=tariffs(ctx['params'].get('tariffs',DEFAULT_TARIFFS));max_hours=number(ctx['params']['max_hours']);loss_rate=number(ctx['params']['loss_rate']);tol=number(ctx['params']['bill_tolerance'])
    if max_hours<=0 or max_hours>168 or loss_rate<0 or tol<0:raise DomainError('RANGE','结算参数无效')
    good=[]
    for row in ctx['records']:
        try:good.append(normalize(row,max_hours))
        except DomainError as exc:ctx['quarantine'].append(rejected(row,exc.code,exc.message))
    good,bad=dedup(good);ctx['quarantine'].extend(bad);ctx['records']=good;ctx['tariffs']=rates
    display=[{'valid_from':x['from'].isoformat(),'valid_to':x['to'].isoformat(),'hours':repr(x['hours'])} for x in rates]
    ctx['stages'].append({'title':'分时费率','rows':display,'metrics':{'版本':len(rates),'有效计量':len(good),'损耗单价':str(loss_rate)}});return ctx
