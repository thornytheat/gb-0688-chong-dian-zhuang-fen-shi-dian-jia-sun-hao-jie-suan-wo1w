from .rules import compare
from app.normalize import number
def execute(ctx):
    rows=compare(ctx['charges'],number(ctx['params']['bill_tolerance']));ctx['bills']=rows
    ctx['stages'].append({'title':'账单对照','rows':rows,'metrics':{'差异单':sum(r['state']!='通过' for r in rows),'账单 CNY':str(sum((r['bill'] for r in rows),0)),'差额 CNY':str(sum((r['delta'] for r in rows),0))}});return ctx
