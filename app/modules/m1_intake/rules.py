from app.normalize import rows_from
from app.reasons import rejected
def receive(raw):
    ctx=rows_from(raw,['id','station','order','start','end','energy','unit','bill','version','kind']);good=[]
    for row in ctx['raw']:
        if not row['id'] or not row['station']:ctx['quarantine'].append(rejected(row,'MISSING','读数或站点号缺失'))
        else:good.append(row)
    ctx['records']=good
    return ctx
