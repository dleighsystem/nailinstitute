"""Independent expected-output comparison and adversarial verification controls."""
import copy, json
from pathlib import Path
from check import check
ROOT = Path(__file__).resolve().parent
b=json.loads((ROOT/'export.json').read_text()); s=json.loads((ROOT/'scenario.json').read_text())
k=(ROOT/'public-key.hex').read_text().strip()
e=json.loads((ROOT/'expected.json').read_text())
a=check(b,s,k)
for field in ['integrity','same_decision_content_distinct_attempts']:
    assert a[field] == e[field], field
for actual, expected in zip(a['attempts'],e['attempts'], strict=True):
    for field, value in expected.items(): assert actual[field] == value, field
controls={}
x=copy.deepcopy(b); x['entries'][0]['payload']['outcome']='changed'
controls['changed_payload']=check(x,s,k)['integrity']
x=copy.deepcopy(b); x['entries'].pop()
controls['dropped_tail']=check(x,s,k)['integrity']
controls['wrong_key']=check(b,s,'00'*32)['integrity']
x=copy.deepcopy(b); x['entries'][0]['payload']['action_id']='synthetic-approved-attempt'
controls['swapped_attempt']=check(x,s,k)['integrity']
assert controls == e['negative_controls'], controls
print('PASS: independent expected verdicts; 4/4 negative controls rejected')
