from .rules import charges
from app.normalize import number
def execute(ctx):
    ctx['charges']=charges(ctx['orders'],ctx['segments'],number(ctx['params']['loss_rate']))
    ctx['stages'].append({'title':'费用重算','rows':ctx['charges'],'metrics':{'应收 CNY':str(sum((x['amount'] for x in ctx['charges']),0)),'分录':len(ctx['charges']),'损耗单价':ctx['params']['loss_rate']}});return ctx
