from decimal import Decimal as D
from collections import defaultdict
def _union(intervals):
    """Return merged [start,end) intervals and whether any input overlap existed."""
    merged=[];overlap=False
    for start,end in sorted(intervals):
        if merged and start<merged[-1][1]:overlap=True;merged[-1]=(merged[-1][0],max(merged[-1][1],end))
        elif merged and start==merged[-1][1]:merged[-1]=(merged[-1][0],end)
        else:merged.append((start,end))
    return merged,overlap
def _covered(start,end,windows):
    cursor=start
    for a,b in windows:
        if b<=cursor:continue
        if a>cursor:return False
        cursor=max(cursor,b)
        if cursor>=end:return True
    return cursor>=end
def allocate(rows):
    stations=defaultdict(list)
    for row in rows:stations[row['station']].append(row)
    assigned=[];balances=[]
    for station,group in sorted(stations.items()):
        orders=[r for r in group if r['kind']=='order'];meters=[r for r in group if r['kind']=='station']
        consumed=sum((r['energy'] for r in orders),D(0));meter=sum((r['energy'] for r in meters),D(0));loss=meter-consumed
        windows,overlap=_union([(r['start'],r['end']) for r in meters])
        state='通过'
        if not meters:state='总表缺失'
        elif overlap:state='总表区间重叠'
        elif any(not _covered(r['start'],r['end'],windows) for r in orders):state='总表未覆盖订单区间'
        elif loss<0:state='订单电量超过总表'
        elif consumed==0 and loss>0:state='无订单承接损耗'
        shares=[loss*r['energy']/consumed if consumed and state=='通过' else D(0) for r in orders]
        if shares and state=='通过':shares[-1]+=loss-sum(shares,D(0))
        for i,row in enumerate(orders):assigned.append({**row,'loss_kwh':shares[i],'loss_state':state})
        balances.append({'station':station,'meter_kwh':meter,'order_kwh':consumed,'loss_kwh':loss,'state':state,'meter_count':len(meters)})
    return assigned,balances
