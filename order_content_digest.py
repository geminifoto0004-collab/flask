"""Canonical row evidence shared by SQLite publisher and TiDB verifier."""
import base64
from decimal import Decimal
import hashlib
import json
import math


def scalar(value, declared):
    if value is None: return None
    if isinstance(value, dict) and set(value)=={'__bytes__'}:
        value=base64.b64decode(value['__bytes__'],validate=True)
    kind=str(declared or '').upper()
    if 'BLOB' in kind or isinstance(value,(bytes,bytearray,memoryview)):
        return ['bytes',(value if isinstance(value,(bytes,bytearray,memoryview)) else str(value).encode()).hex()]
    if 'INT' in kind or 'BOOL' in kind: return str(int(value))
    if any(part in kind for part in ('NUMERIC','DECIMAL')):
        return format(Decimal(str(value)).normalize(),'f')
    if any(part in kind for part in ('REAL','FLOA','DOUB')):
        number=float(value)
        if not math.isfinite(number): raise ValueError('non-finite numeric value')
        return format(number,'.17g')
    return str(value)


def digest_rows(columns, rows, limit=500000):
    hashes=[]
    for row in rows:
        if len(hashes)>=limit: raise ValueError('content row limit exceeded')
        values=[scalar(row.get(col['name']) if isinstance(row,dict) else row[index],col.get('type')) for index,col in enumerate(columns)]
        raw=json.dumps(values,ensure_ascii=False,separators=(',',':')).encode()
        hashes.append(hashlib.sha256(raw).digest())
    digest=hashlib.sha256(json.dumps(columns,sort_keys=True,separators=(',',':')).encode())
    for value in sorted(hashes): digest.update(value)
    return {'rows':len(hashes),'digest':digest.hexdigest()}
