import ast
from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time
import types

import pytest
from flask import Flask, Blueprint

ROOT=Path(__file__).resolve().parents[1]
REMOTE=ROOT
HOST=ROOT/'work255/home/FlaskApp2025'
sys.path.insert(0,str(REMOTE));sys.path.insert(0,str(HOST))
import tidb_integrity as evidence


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result);return result


def function(path,name,namespace,cls=None):
    tree=ast.parse(path.read_text(encoding='utf-8-sig'))
    nodes=tree.body if cls is None else next(n.body for n in tree.body if isinstance(n,ast.ClassDef) and n.name==cls)
    node=next(n for n in nodes if isinstance(n,ast.FunctionDef) and n.name==name)
    node.decorator_list=[]
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),namespace)
    return namespace[name]


@pytest.fixture(autouse=True)
def clean_evidence():
    evidence._evidence={'state':'unverified','verified':False,'targets':{},'differences':[]}
    evidence._blocked.clear();evidence._writers.clear()


def verified():
    return {'state':'verified','verified':True,'cloud_equal':True,'order_equal':True,
            'targets':{'TIDB1':{'reachable':True},'TIDB2':{'reachable':True}}}


def test_guard_fails_closed_then_accepts_current_proof():
    assert not evidence.can_promote('TIDB1')
    evidence.publish(verified(),evidence.generation())
    assert evidence.can_promote('TIDB1')
    evidence.invalidate()
    assert not evidence.can_promote('TIDB1')


def test_late_verification_cannot_revalidate_new_writes():
    generation=evidence.generation();evidence.invalidate()
    result=evidence.publish(verified(),generation)
    assert not result['verified'] and result['state']=='changed_during_check'


def test_quota_circuit_and_no_credential_fields():
    evidence.publish(verified(),evidence.generation())
    evidence.target_failed('TIDB1',RuntimeError('Request Unit budget exceeded'))
    assert evidence.target_blocked('TIDB1') and not evidence.can_promote('TIDB1')
    assert evidence.can_promote('TIDB2')
    assert set(evidence.snapshot())<={'state','verified','cloud_equal','order_equal','targets','checked_at_epoch','unavailable_cooldown_targets'}


def test_read_timeout_quarantines_target_but_sql_validation_error_does_not():
    evidence.target_failed('TIDB1',TimeoutError('read timed out'))
    evidence.target_failed('TIDB2',ValueError('invalid SQL'))
    assert evidence.target_blocked('TIDB1') and not evidence.target_blocked('TIDB2')


def test_wrong_scope_and_expired_proof():
    value=verified();value['order_equal']=False
    evidence.publish(value,evidence.generation())
    assert not evidence.can_promote('TIDB2','order')
    evidence._evidence['checked_at_epoch']=time.time()-901
    assert not evidence.can_promote('TIDB2')


def test_grant_requires_valid_signature_and_scope():
    grant=module('grant_test',REMOTE/'services/order_desktop_grant.py')
    app=Flask('grant');app.secret_key='unit-test-only'
    with app.app_context(): token=grant.issue()
    with app.test_request_context(headers={'X-Order-Desktop-Grant':token}): assert grant.authorized()
    with app.test_request_context(headers={'X-Order-Desktop-Grant':token+'bad'}): assert not grant.authorized()
    with app.test_request_context(): assert not grant.authorized()
    from itsdangerous import URLSafeTimedSerializer
    wrong=URLSafeTimedSerializer(app.secret_key,salt=grant.SALT).dumps({'scope':'write','device':'x'})
    with app.test_request_context(headers={'X-Order-Desktop-Grant':wrong}): assert not grant.authorized()


def test_link_grant_cannot_authorize_replica_repair():
    grant=module('scoped_grants',REMOTE/'services/order_desktop_grant.py')
    app=Flask('scope');app.secret_key='test'
    with app.app_context():
        read=grant.issue();sync=grant.issue('replicas:verify-repair')
    with app.test_request_context(headers={'X-Order-Desktop-Sync-Grant':read}):assert not grant.authorized('replicas:verify-repair')
    with app.test_request_context(headers={'X-Order-Desktop-Sync-Grant':sync}):assert grant.authorized('replicas:verify-repair')
    with app.test_request_context(headers={'X-Order-Desktop-Grant':sync}):assert not grant.authorized()


def test_digest_order_independent_and_detects_permission_difference():
    audit=module('audit_test',REMOTE/'services/order_sync_integrity.py')
    class Cursor:
        def __init__(self,rows): self.rows=rows;self.done=False
        def execute(self,sql,*args): self.sql=sql;self.done=False
        def fetchone(self): return {'exists':1}
        def fetchall(self): return [{'Field':'token_hash'},{'Field':'order_number'},{'Field':'show_order'}]
        def fetchmany(self,size):
            if self.done:return []
            self.done=True;return self.rows
    class Conn:
        def __init__(self,rows):self.rows=rows
        def cursor(self):return Cursor(self.rows)
    rows=[{'token_hash':'a','order_number':'1','show_order':False},{'token_hash':'a','order_number':'2','show_order':True}]
    a=audit.table_digest(Conn(rows),'cloud_share_order_visibility')
    assert a==audit.table_digest(Conn(list(reversed(rows))),'cloud_share_order_visibility')
    other=[dict(row) for row in rows];other[0]['show_order']=True
    assert a!=audit.table_digest(Conn(other),'cloud_share_order_visibility')
    with pytest.raises(RuntimeError,match='row limit'):audit.table_digest(Conn(rows),'cloud_share_order_visibility',limit=1)


def test_preflight_fallback_requires_verified_backup():
    calls=[]
    class Connection:
        def cursor(self):return self
        def execute(self,sql):calls.append(sql)
        def fetchone(self):return (1,)
        def rollback(self):pass
        def close(self):pass
    def raw(target,**kwargs):
        if target=='TIDB1':raise RuntimeError('Request Unit quota exceeded')
        return Connection()
    ns={'tidb_preferred_target':lambda:'TIDB1','get_cloud_mirror_source_hint':lambda:None,
        'tidb_failover_enabled':lambda:True,'tidb_selected_target':lambda:'AUTO',
        'tidb_target_candidates':lambda *a,**k:['TIDB1','TIDB2'],'tidb_target_configured':lambda x:True,
        'AdaptedConnection':lambda x:x,'_raw_mysql_connection_for_target':raw}
    fn=function(REMOTE/'database.py','_select_mysql_connection',ns)
    with pytest.raises(RuntimeError,match='standby_not_verified'):fn()
    evidence.publish(verified(),evidence.generation())
    assert fn()[1]=='TIDB2' and calls==['SELECT 1']


def test_failed_write_is_not_replayed():
    calls=[]
    class Cursor:
        def execute(self,*args):calls.append(args);raise RuntimeError('Request Unit limit')
    ns={'_is_cloud_write':lambda sql:True}
    fn=function(REMOTE/'database.py','execute',ns,'CloudMirroredCursor')
    cursor=types.SimpleNamespace(_active_cursor=Cursor(),_connection=types.SimpleNamespace(active_target='TIDB1'))
    with pytest.raises(RuntimeError):fn(cursor,'UPDATE cloud_orders SET active=0')
    assert len(calls)==1 and evidence.target_blocked('TIDB1')


def test_unchanged_rows_not_upserted_and_composite_keys_preserved():
    source=[{'token_hash':'a','order_number':'1','show_order':True},{'token_hash':'a','order_number':'2','show_order':False}]
    dest=[dict(source[0]),dict(source[1],show_order=True)]
    class Cur:
        def __init__(self,rows):self.rows=rows;self.writes=[];self.done=False
        def execute(self,sql,*a):self.done=False
        def fetchmany(self,n):
            if self.done:return []
            self.done=True;return self.rows
        def executemany(self,sql,values):self.writes.extend(values)
    class Conn:
        def __init__(self,rows):self.cur=Cur(rows)
        def cursor(self):return self.cur
        def commit(self):pass
    a,b=Conn(source),Conn(dest)
    ns={'_table_exists':lambda *a:True,'_ensure_destination_schema':lambda *a:None,
        '_PRIMARY_KEYS':{'cloud_share_order_visibility':('token_hash','order_number')},
        '_IDENT':__import__('re').compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$'),'_qi':lambda x:'`'+x+'`'}
    fn=function(REMOTE/'services/order_tidb_cloud_reconcile.py','_upsert_table',ns)
    result=fn(a,b,'cloud_share_order_visibility')
    assert result['rows']==2 and result['changed']==1
    assert b.cur.writes==[('a','2',False)]












def test_cloud_integrity_post_requires_paired_grant(monkeypatch):
    app=Flask('api');app.secret_key='test'
    bp=Blueprint('test',__name__)
    parent=types.ModuleType('blueprints');parent.__path__=[]
    auth=types.ModuleType('blueprints.b2_test_bp');auth._order_cloud_auth_source=lambda:('test',None)
    targets=types.ModuleType('tidb_targets');targets.selected_target=lambda:'TIDB2';targets.target_configured=lambda x:True;targets.mirror_enabled=lambda:True
    services=types.ModuleType('services');services.__path__=[str(REMOTE/'services')]
    for obj in [parent,auth,targets,services]:monkeypatch.setitem(sys.modules,obj.__name__,obj)
    audit=module('api_integrity',REMOTE/'services/order_sync_integrity.py');audit.install(bp)
    app.register_blueprint(bp);client=app.test_client()
    assert client.get('/api/order-cloud/sync/integrity').status_code==401
    assert client.post('/api/order-cloud/sync/integrity',json={'repair':True}).status_code==401


def test_local_sqlite_and_tidb_numeric_blob_values_have_same_content_proof():
    from decimal import Decimal
    from order_content_digest import digest_rows
    columns=[{'name':'n','type':'NUMERIC'},{'name':'f','type':'REAL'},{'name':'b','type':'BLOB'},{'name':'i','type':'INTEGER'}]
    local=[[1.5,2.0,{'__bytes__':'YWJj'},3]]
    remote=[{'n':Decimal('1.5000000000'),'f':2.0,'b':b'abc','i':3}]
    assert digest_rows(columns,local)==digest_rows(columns,remote)
    remote[0]['i']=4
    assert digest_rows(columns,local)!=digest_rows(columns,remote)


def test_content_proof_preserves_null_and_row_multiplicity():
    from order_content_digest import digest_rows
    columns=[{'name':'n','type':'INTEGER'}]
    assert digest_rows(columns,[[None]])!=digest_rows(columns,[[0]])
    assert digest_rows(columns,[[1]])!=digest_rows(columns,[[1],[1]])


@pytest.mark.parametrize('second_value,changed,enabled,ok',[(1,False,True,True),(2,False,True,False),(1,True,True,False),(1,False,False,False)])
def test_complete_verifier_checks_local_contents_stability_and_enabled_state(monkeypatch,second_value,changed,enabled,ok):
    from order_content_digest import digest_rows
    audit=module('verification_matrix',REMOTE/'services/order_sync_integrity.py')
    class Connection:
        def __init__(self,target):self.target=target;self.done=False
        def cursor(self):return self
        def execute(self,sql,*args):self.sql=sql;self.done=False
        def fetchone(self):return {'snapshot_hash':'same','table_count':1,'row_count':1}
        def fetchall(self):return [{'table':'orders'}]
        def fetchmany(self,count):
            if self.done:return []
            self.done=True;return [{'n':second_value if self.target=='TIDB2' else 1}]
        def close(self):pass
    database=types.ModuleType('database');database.get_db_connection_for_target=lambda target,**kw:Connection(target)
    targets=types.ModuleType('tidb_targets');targets.target_configured=lambda x:True;targets.mirror_enabled=lambda:enabled
    repair=types.ModuleType('services.order_tidb_cloud_reconcile');repair._TABLES=['cloud_orders','cloud_share_order_visibility','cloud_tidb_mirror_state'];repair._STATE_TABLE='cloud_tidb_mirror_state'
    count={'value':0}
    def version(target):
        count['value']+=1
        return 6 if changed and count['value']>=3 else 5
    repair._mirror_version=version
    connections=types.ModuleType('services.order_tidb_connection');connections._connect_target=lambda target,**kw:Connection(target);connections.order_database_name=lambda:'order_tracking'
    mirror=types.ModuleType('services.order_full_mirror_service');mirror._STATE_TABLE='__order_mirror_state'
    for mod in [database,targets,repair,connections,mirror]:monkeypatch.setitem(sys.modules,mod.__name__,mod)
    audit.table_digest=lambda *a,**k:{'exists':True,'rows':1,'digest':'same'}
    columns=[{'name':'n','type':'INTEGER'}]
    expected={'orders':{'columns':columns,**digest_rows(columns,[[1]])}}
    result=audit.verify_once(expected)
    assert result['verified'] is ok
    assert result['local_equal'] is (second_value==1)


@pytest.mark.parametrize('changed',[False,True])
def test_backup_alignment_preserves_old_tables_and_aborts_source_changes(monkeypatch,changed):
    statements=[]
    class Cursor:
        def __init__(self,target):self.target=target;self.done=False
        def execute(self,sql,*a):self.done=False;statements.append((self.target,sql))
        def fetchmany(self,n):
            if self.done:return []
            self.done=True;return [{'id':1}]
        def executemany(self,sql,rows):statements.append((self.target,sql))
    class Connection:
        def __init__(self,target):self.target=target
        def cursor(self):return Cursor(self.target)
        def commit(self):pass
        def close(self):pass
    counter={'n':0}
    def version(target):counter['n']+=1;return 2 if changed and counter['n']>1 else 1
    helper=types.ModuleType('services.order_sync_integrity');helper.table_digest=lambda *a:{'exists':True,'rows':1,'digest':'same'}
    monkeypatch.setitem(sys.modules,helper.__name__,helper)
    ns={'_reconcile_lock':threading.Lock(),'get_db_connection_for_target':lambda target,**kw:Connection(target),
        'other_target':lambda target:'TIDB1','_mirror_version':version,'_TABLES':['cloud_orders'],
        '_table_exists':lambda *a:True,'_show_create':lambda *a:'CREATE TABLE `cloud_orders` (`id` bigint)',
        '_qi':lambda x:'`'+x+'`','re':__import__('re'),'_invalidate_derived_views':lambda *a:None,'_invalidate_process_views':lambda:None}
    fn=function(REMOTE/'services/order_tidb_cloud_reconcile.py','align_verified_backup',ns)
    if changed:
        with pytest.raises(RuntimeError,match='source_changed'):fn('TIDB2')
        assert not any(sql.startswith('RENAME TABLE') for _,sql in statements)
    else:
        result=fn('TIDB2');assert result['preserved'] and 'cloud_orders' in result['archives']
        renames=[sql for _,sql in statements if sql.startswith('RENAME TABLE')]
        assert len(renames)==1 and '`cloud_orders` TO `__v255_archive_' in renames[0]
    assert not any('DROP TABLE IF EXISTS `cloud_orders`' in sql or 'DROP TABLE IF EXISTS `__v255_archive_' in sql for _,sql in statements)


def test_order_backup_archives_tables_outside_current_manifest(monkeypatch):
    statements=[]
    class Connection:
        def __init__(self,target):self.target=target;self.done=False
        def cursor(self):return self
        def execute(self,sql,*a):self.sql=sql;self.done=False;statements.append(sql)
        def fetchone(self):return {'snapshot_hash':'same'}
        def fetchall(self):return [{'table':'orders'},{'table':'legacy_only'},{'table':'__order_mirror_state'}]
        def fetchmany(self,n):
            if self.done:return []
            self.done=True;return [{'id':1}]
        def executemany(self,sql,rows):statements.append(sql)
        def commit(self):pass
        def close(self):pass
    database=types.ModuleType('database');database.AdaptedConnection=lambda conn:conn
    connection=types.ModuleType('services.order_tidb_connection');connection._connect_target=lambda target,**kw:Connection(target);connection.order_database_name=lambda:'order_tracking'
    state=types.ModuleType('services.order_full_mirror_service');state._STATE_TABLE='__order_mirror_state'
    helper=types.ModuleType('services.order_sync_integrity');helper.table_digest=lambda *a:{'exists':True,'rows':1,'digest':'same'}
    for mod in [database,connection,state,helper]:monkeypatch.setitem(sys.modules,mod.__name__,mod)
    ns={'_reconcile_lock':threading.Lock(),'other_target':lambda target:'TIDB1','_show_create':lambda c,t:'CREATE TABLE `'+t+'` (`id` bigint)', '_qi':lambda x:'`'+x+'`','re':__import__('re')}
    fn=function(REMOTE/'services/order_tidb_cloud_reconcile.py','align_order_backup',ns)
    result=fn('TIDB2',{'orders':{}})
    assert result['preserved'] and 'legacy_only' in result['archives']
    assert sum(sql.startswith('RENAME TABLE') for sql in statements)==1
    assert not any(sql.startswith('DROP TABLE') for sql in statements)
