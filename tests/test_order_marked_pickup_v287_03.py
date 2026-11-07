"""V287-03: offline read-only regression tests; no live TiDB/B2/Access."""
import ast
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]


def load(path,name,ns):
    tree=ast.parse((ROOT/path).read_text(encoding='utf-8'))
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    fn.decorator_list=[]
    exec(compile(ast.Module(body=[fn],type_ignores=[]),path,'exec'),ns)
    return ns[name]


class MarkedPickup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lifecycle={'datetime':datetime}
        from zoneinfo import ZoneInfo
        cls.lifecycle['ZoneInfo']=ZoneInfo
        cls.is_bulk_photo=load('services/order_media_lifecycle.py','is_bulk_photo',cls.lifecycle)
        cls.customer_pickup_visibility=load('services/order_media_lifecycle.py','customer_pickup_visibility',cls.lifecycle)
        ns={'source_match':lambda asset,order:next((s for s in order.get('image_sources',[])
             if s['sha256']==asset['sha256'] and s.get('workflow_key','')==asset.get('workflow_key','')),False),
            '_is_image':lambda asset:asset.get('asset_type')=='IMAGE',
            '_route':lambda token,asset:'/share/'+token+'/image/'+asset.get('asset_key',''),
            'is_bulk_photo':cls.is_bulk_photo}
        cls.images=load('services/order_share_native_order_ui.py','_images',ns)
        cls.covers=load('services/order_share_native_order_ui.py','_cover_assets',ns)

    def sample(self,tag=True):
        a={'asset_type':'IMAGE','asset_key':'a'*64,'sha256':'a'*64,'workflow_key':'WF1','object_key':'one'}
        b={'asset_type':'IMAGE','asset_key':'b'*64,'sha256':'b'*64,'workflow_key':'WF1','object_key':'two'}
        order={'order_number':'O1','assets':[a,b],'workflows':[{'workflow_key':'WF1'}],
               'image_sources':[{'sha256':'a'*64,'workflow_key':'WF1','attachment_purpose':'general'},
               {'sha256':'b'*64,'workflow_key':'WF1','attachment_purpose':'bulk_photo' if tag else 'general'}]}
        return order,a,b

    def test_marked_asset_first_and_customer_has_no_mark(self):
        order,a,b=self.sample()
        result=self.images(order,order['workflows'][0],'t')
        self.assertTrue(result[0]['url'].endswith(b['asset_key']))
        self.assertNotIn('attachment_purpose',str(result))
        self.assertNotIn('_marked_for_sort',str(result))

    def test_unmark_reverts_without_new_bytes(self):
        order,a,b=self.sample(tag=False)
        result=self.images(order,order['workflows'][0],'t')
        self.assertTrue(result[0]['url'].endswith(a['asset_key']))

    def test_cover_uses_marked_asset(self):
        order,a,b=self.sample()
        selected=self.covers({'orders':[order]})
        self.assertEqual(selected[0]['sha256'],b['sha256'])

    def test_same_sha_one_tagged_source_still_tagged(self):
        order,a,b=self.sample()
        order['image_sources'].append({'sha256':'a'*64,'workflow_key':'WF1','attachment_purpose':'bulk_photo'})
        self.assertTrue(self.is_bulk_photo(a,order))

    def test_missing_metadata_defaults_general(self):
        order,a,b=self.sample()
        order['image_sources']=[]
        self.assertFalse(self.is_bulk_photo(a,order))

    def pickup(self,last='2026-09-01',all_picked=True):
        return {'all_picked_up':all_picked,'last_pickup_date':last,'workflows':[{'status':'COMPLETED'}],
                'logistics':[{'status':'ARRIVED_IQUIQUE','pickup_status':'picked_up'}]}

    def test_one_calendar_month_is_hide_not_three_months(self):
        clock=datetime.fromisoformat('2026-11-07T12:00:00-03:00')
        self.assertEqual(self.customer_pickup_visibility(self.pickup(),now=clock),'hide')
        self.assertEqual(self.customer_pickup_visibility(self.pickup('2026-10-20'),now=clock),'keep_recent_pickup')

    def test_missing_last_date_fails_open(self):
        clock=datetime.fromisoformat('2026-11-07T12:00:00-03:00')
        self.assertEqual(self.customer_pickup_visibility(self.pickup(''),now=clock),'keep_unknown')

    def test_reversed_pickup_restores_visibility(self):
        clock=datetime.fromisoformat('2026-11-07T12:00:00-03:00')
        self.assertEqual(self.customer_pickup_visibility(self.pickup(all_picked=False),now=clock),'keep_unknown')

    def test_partial_and_in_transit_never_hide(self):
        clock=datetime.fromisoformat('2026-11-07T12:00:00-03:00')
        p=self.pickup()
        p['logistics'].append({'status':'IN_TRANSIT','pickup_status':''})
        self.assertEqual(self.customer_pickup_visibility(p,now=clock),'keep_unknown')
        p=self.pickup()
        p['logistics'].append({'status':'ARRIVED_IQUIQUE','pickup_status':'pending_pickup'})
        self.assertEqual(self.customer_pickup_visibility(p,now=clock),'keep_unknown')

    def test_not_completed_does_not_hide(self):
        p=self.pickup()
        p['workflows'][0]['status']='IN_PRODUCTION'
        self.assertEqual(self.customer_pickup_visibility(p),'keep_unknown')

    def test_manual_hidden_is_still_excluded(self):
        # Source check prevents an automatic derived marker from setting a
        # manual show_order value: _filter_space uses it before pickup rule.
        source=(ROOT/'services/order_public_share_fast.py').read_text(encoding='utf-8')
        start=source.index("override.get('show_order') is False")
        end=source.index("pickup_view = customer_pickup_visibility(order)",start)
        self.assertLess(start,end)
        self.assertNotIn('show_order=',source[end:end+1000])

if __name__=='__main__':
    unittest.main()
