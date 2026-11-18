from decimal import Decimal as D,ROUND_HALF_UP,ROUND_FLOOR
from collections import defaultdict
def charges(orders,segments,loss_rate):
    fees=defaultdict(lambda:D(0))
    for row in segments:fees[row['id']]+=row['fee']
    by_station=defaultdict(list)
    for row in orders:by_station[row['station']].append({**row,'raw_amount':fees[row['id']]+row['loss_kwh']*loss_rate})
    result=[]
    for station,group in sorted(by_station.items()):
        target=sum((r['raw_amount'] for r in group),D(0)).quantize(D('.01'),rounding=ROUND_HALF_UP)
        amounts=[r['raw_amount'].quantize(D('.01'),rounding=ROUND_FLOOR) for r in group]
        pennies=int((target-sum(amounts,D(0)))/D('.01'));order=sorted(range(len(group)),key=lambda i:(-(group[i]['raw_amount']-amounts[i]),group[i]['id']))
        for i in order[:pennies]:amounts[i]+=D('.01')
        result.extend({**row,'amount':amounts[i],'state':row['loss_state']} for i,row in enumerate(group))
    return result
