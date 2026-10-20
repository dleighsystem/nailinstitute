"""Bounded synthetic-vector checker v1; not the unavailable Apex policy checker or GALC verifier."""
import hashlib, json, sys
from pathlib import Path
from datetime import datetime
from integrity import digest, verify_bundle
ROOT = Path(__file__).resolve().parent
RULE = 'neuravant-synthetic-pair/v1'

def verdict(values):
    return 'VIOLATION' if False in values else ('INSUFFICIENT_EVIDENCE' if None in values else 'NO_VIOLATION')

def check(bundle, scenario, public_key):
    entries = bundle['entries']
    valid = verify_bundle(bundle, scenario['tenant_id'], scenario['agent_id'], public_key)
    if not valid:
        return {'integrity': 'FAIL', 'attempts': []}
    rh = digest(dict(surface='openshell-middleware/v1', upstream=scenario['upstream'],
                        tool=scenario['tool'], arguments=scenario['arguments']))
    results = []
    decisions = []
    for action in scenario['attempts']:
        rows = [e for e in entries if e['payload']['action_id'] == action]
        phases = {e['payload']['phase']: e['payload'] for e in rows}
        # A duplicate phase is ambiguous, even if individually signed.
        assert len(phases) == len(rows), 'duplicate phase'
        dec = json.loads(phases['decision']['outcome']) if 'decision' in phases else {}
        scope = json.loads(phases['scope']['outcome']) if 'scope' in phases else {}
        bound = all(p['request_hash'] == rh and p['tool'] == scenario['tool'] for p in phases.values())
        decision_ok = bool(dec) and dec.get('arguments_sha256') == digest(scenario['arguments']) and dec.get('decision_sha256') == rh
        decisions.append(dec.get('decision_sha256'))
        scope_values = []
        for field, target in [('allowed_tenant_id','tenant_id'), ('allowed_resource_id','resource_id')]:
            scope_values.append(None if scope.get(field) is None or target not in scenario['arguments'] else scope[field] == scenario['arguments'][target])
        grant = json.loads(phases['grant']['outcome']) if 'grant' in phases else None
        intent = phases.get('intent')
        if 'denied' in phases and intent is None and grant is None:
            approval_values = [False]  # No authorization to dispatch this denied attempt; denial is expected enforcement.
        elif grant and intent:
            audit = [e['payload'] for e in entries if e['payload']['action_id'] == grant.get('approval_id') and e['payload']['tool'] == 'human_approval']
            approval_values = [grant.get('consumed_action_id') == action,
                grant.get('approval_id') == intent.get('approval_id'),
                grant.get('approved_arguments_sha256') == digest(scenario['arguments']),
                grant.get('allowed_tenant_id') == scenario['tenant_id'], grant.get('tool') == scenario['tool'],
                grant.get('consumed_at', float('inf')) < grant.get('expires_at', 0),
                len(audit) == 1 and audit[0]['request_hash'] == rh and audit[0]['policy_version'] == intent['policy_version']
                and audit[0]['outcome'] == 'approved:' + grant.get('approver_id',''),
                sum(e['payload']['phase'] == 'intent' and e['payload'].get('approval_id') == grant.get('approval_id') for e in entries) == 1]
        else:
            approval_values = [None]
        results.append({'action_id': action, 'decision_binding': 'PASS' if bound and decision_ok else 'FAIL',
                        'approval_policy': verdict(approval_values), 'tenant_resource_policy': verdict(scope_values),
                        'enforcement': 'DENIED' if 'denied' in phases else 'INTENT_RECORDED',
                        'reported_outcome': phases.get('outcome',{}).get('outcome'),
                        'record_refs': {e['payload']['phase']:e['entry_hash'] for e in rows}})
    return {'integrity':'PASS', 'same_decision_content_distinct_attempts': len(set(scenario['attempts'])) == 2 and len(set(decisions)) == 1 and decisions[0] == rh,
            'attempts':results, 'external_effect':'NOT_EVALUATED', 'authority_identity':'NOT_EVALUATED',
            'anchoring':'NOT_EVALUATED', 'custody':'NOT_EVALUATED', 'galc_conformance':'NOT_EVALUATED'}

def main():
    result = check(json.loads((ROOT/'export.json').read_text()), json.loads((ROOT/'scenario.json').read_text()),
                   (ROOT/'public-key.hex').read_text().strip())
    result['rule_revision'] = RULE
    result['source_sha256'] = {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['check.py','integrity.py']}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result['integrity'] == 'PASS' and all(a['decision_binding']=='PASS' for a in result['attempts']) else 1
if __name__ == '__main__': sys.exit(main())
