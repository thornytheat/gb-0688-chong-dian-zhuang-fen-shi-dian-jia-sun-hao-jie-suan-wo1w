from decimal import Decimal as D
from collections import defaultdict
def allocate(rows):
    stations=defaultdict(list)
    for row in rows:stations[row['station']].append(row)
    assigned=[];balances=[]
    for station,group in sorted(stations.items()):
        orders=[r for r in group if r['kind']=='order'];meters=[r for r in group if r['kind']=='station']
        consumed=sum((r['energy'] for r in orders),D(0));meter=sum((r['energy'] for r in meters),D(0));loss=meter-consumed
        state='通过'
        if len(meters)!=1:state='总表缺失或重复'
        elif any(r['start']<meters[0]['start'] or r['end']>meters[0]['end'] for r in orders):state='总表未覆盖订单区间'
        elif loss<0:state='订单电量超过总表'
        elif consumed==0 and loss>0:state='无订单承接损耗'
        shares=[loss*r['energy']/consumed if consumed and state=='通过' else D(0) for r in orders]
        if shares and state=='通过':shares[-1]+=loss-sum(shares,D(0))
        for i,row in enumerate(orders):assigned.append({**row,'loss_kwh':shares[i],'loss_state':state})
        balances.append({'station':station,'meter_kwh':meter,'order_kwh':consumed,'loss_kwh':loss,'state':state})
    return assigned,balances
