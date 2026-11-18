from decimal import Decimal as D
def compare(rows,tolerance):
    return [{**row,'delta':row['amount']-row['bill'],'state':'通过' if abs(row['amount']-row['bill'])<=tolerance and row['loss_state']=='通过' else '待复核'} for row in rows]
