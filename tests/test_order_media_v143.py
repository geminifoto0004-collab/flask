import importlib.util
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import unittest
ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
policy=load('media_policy',ROOT/'services/order_share_image_policy.py')
lifecycle=load('media_lifecycle',ROOT/'services/order_media_lifecycle.py')
class MediaLifecycleTests(unittest.TestCase):
 def setUp(self):
  self.asset={'workflow_key':'wf','sha256':'s'}
  self.order={'order_status':'ACTIVE','image_sources_authoritative':True,'image_sources':[{'workflow_key':'wf','sha256':'s','uploaded_at_epoch':1}], 'workflows':[{'workflow_key':'wf','status':'COMPLETED','last_status_change_date':'2026-06-01'}], 'logistics':[{'status':'ARRIVED_IQUIQUE','pickup_status':'picked_up'}]}
  self.now=datetime(2026,10,14,tzinfo=ZoneInfo('America/Santiago'))
 def test_deleted_or_hidden_file_disappears_despite_old_b2_asset(self):
  self.order['image_sources']=[];self.order['assets']=[self.asset]
  policy.filter_assets_in_space({'orders':[self.order]},{});self.assertEqual(self.order['assets'],[])
 def test_same_hash_different_workflow_is_not_the_same_attachment(self):
  self.assertFalse(policy.source_match(dict(self.asset,workflow_key='other'),self.order))
 def test_latest_sqlite_source_date_wins_without_using_b2_date(self):
  self.order['image_sources'].append({'workflow_key':'wf','sha256':'s','uploaded_at_epoch':100})
  self.assertEqual(policy.source_match(dict(self.asset,created_at='2099-01-01'),self.order)['uploaded_at_epoch'],100)
 def test_completed_old_and_fully_picked_up_is_only_a_candidate(self):
  self.assertEqual(lifecycle.retention_reason(self.order,self.asset,now=self.now),'candidate_completed_over_three_months')
 def test_one_container_not_picked_up_protects_all_order_images(self):
  self.order['logistics'].append({'status':'ARRIVED_IQUIQUE','pickup_status':'pending'})
  self.assertEqual(lifecycle.retention_reason(self.order,self.asset,now=self.now),'keep_pending_iquique_pickup')
 def test_pending_pickup_protects_even_cancelled_order_storage(self):
  self.order['order_status']='CANCELLED';self.order['logistics'][0]['pickup_status']='pending'
  self.assertTrue(lifecycle.retention_reason(self.order,self.asset,now=self.now).startswith('keep_'))
 def test_unknown_or_recent_completion_never_authorizes_cleanup(self):
  for value in [None,'invalid','2026-08-01','2026-07-14']:
   self.order['workflows'][0]['last_status_change_date']=value
   self.assertTrue(lifecycle.retention_reason(self.order,self.asset,now=self.now).startswith('keep_'))
 def test_pending_local_hash_never_authorizes_removal(self):
  self.order['image_sources']=[{'workflow_key':'wf','sha256':''}]
  self.assertEqual(lifecycle.retention_reason(self.order,self.asset,now=self.now),'keep_pending_source_verification')
 def test_old_unmigrated_metadata_needs_sqlite_manifest(self):
  self.order.pop('image_sources_authoritative')
  self.assertEqual(lifecycle.retention_reason(self.order,self.asset,now=self.now),'keep_awaiting_sqlite_manifest')

class SharedB2DeleteTests(unittest.TestCase):
 def test_existing_manual_delete_keeps_shared_object_bytes(self):
  import ast
  from flask import Flask
  from types import SimpleNamespace
  tree=ast.parse((ROOT/'services/order_cloud_asset_admin.py').read_text())
  node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='order_cloud_admin_asset_delete');node.decorator_list=[]
  key='a'*64
  for references,expected_calls in [(1,0),(0,2)]:
   deleted=[]
   class Cursor:
    def execute(self,*args):pass
    def fetchall(self):return [{'asset_key':key,'storage_backend':'b2_primary','sha256':'s'*64,'object_key':'order-cloud/images/a.jpg','thumb_object_key':'order-cloud/thumbs/a.jpg','customer_key':'CLIENT'}]
    def fetchone(self):return {'n':references}
   cur=Cursor();conn=SimpleNamespace(commit=lambda:None,rollback=lambda:None,close=lambda:None)
   app=Flask('gc-test')
   from flask import request,jsonify
   scope=dict(request=request,jsonify=jsonify,_order_cloud_auth_source=lambda:(None,None),_ensure_order_cloud_tables=lambda:None,
     get_db_connection=lambda:conn,get_cursor=lambda c:cur,get_row_dict=lambda row,c:row,
     _asset_select_base=lambda:'SELECT assets',_backend=lambda b:b,PRIMARY='b2_primary',
     _delete_object=lambda b,k:deleted.append(k),_thumb_key_from_sha=lambda s:'thumb',_invalidate_customer_snapshots=lambda c:None)
   exec(compile(ast.Module(body=[node],type_ignores=[]),'<manual-delete>','exec'),scope)
   with app.test_request_context('/',method='POST',json={'asset_keys':[key]}):
    scope['order_cloud_admin_asset_delete']()
   self.assertEqual(len(deleted),expected_calls)
