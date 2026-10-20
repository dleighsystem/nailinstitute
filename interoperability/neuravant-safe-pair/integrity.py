"""Standalone format reader authored for this public synthetic vector.
No Neuravant private implementation is included. Uses Python JSON and the
cryptography library's Ed25519 verification; trusts only the supplied fixture key.
"""
import hashlib
import json
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

def encoded(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')

def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()

def verify_bundle(bundle, tenant, agent, public_key):
    try:
        head = bundle['head']
        rows = bundle['entries']
        fields = {'version','tenant_id','agent_id','first_seq','first_prev_hash','seq','entry_hash','record_count','signed_at','public_key','signature'}
        if set(head) != fields or not rows or head['public_key'] != public_key:
            return False
        # This vector is a complete genesis-starting prefix. Completeness beyond
        # its signed head is explicitly not claimed.
        previous = 'GENESIS'
        for index, row in enumerate(rows, 1):
            p = row['payload']
            if p['version'] != 'runtime-evidence/v1' or p['tenant_id'] != tenant or p['agent_id'] != agent:
                return False
            if p['seq'] != index or p['prev_hash'] != previous or digest(p) != row['entry_hash']:
                return False
            previous = row['entry_hash']
        if (head['version'] != 'export-head/v1' or head['tenant_id'] != tenant or head['agent_id'] != agent
            or head['first_seq'] != 1 or head['first_prev_hash'] != 'GENESIS'
            or head['seq'] != len(rows) or head['record_count'] != len(rows) or head['entry_hash'] != previous):
            return False
        unsigned = {k:v for k,v in head.items() if k != 'signature'}
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key)).verify(bytes.fromhex(head['signature']), encoded(unsigned))
        return True
    except (KeyError, TypeError, ValueError, InvalidSignature):
        return False
