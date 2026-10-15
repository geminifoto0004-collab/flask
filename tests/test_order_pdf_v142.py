"""PDF grouping and source permissions, using only request-owned synthetic data."""
import ast
import importlib.util
import copy
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('pdf_policy',ROOT/'services/order_share_image_policy.py')
policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
filter_assets_in_space=policy.filter_assets_in_space
asset_allowed=policy.asset_allowed

def images(order,workflow=None):
    tree=ast.parse((ROOT/'services/order_share_native_order_ui.py').read_text())
    scope={'_is_image':lambda a:True,'_route':lambda t,a:'/share/token/image/'+a['asset_key']}
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_images')
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<native-images>','exec'),scope)
    return scope['_images'](order,workflow,'token')

class PdfShareTests(unittest.TestCase):
    def sample(self):
        docs=[{'id':f'order-{n}','filename':f'PDF {n}.pdf','uploaded_at':f'2026-10-{n:02}', 'page_count':2,
               'workflow_key':'', 'pages':[{'page':i,'sha256':f'{n}-{i}'} for i in [1,2]]} for n in [1,2,3]]
        assets=[{'order_number':'8403','asset_key':f'{n}{i}'.ljust(64,'0'),'sha256':f'{n}-{i}','content_type':'image/jpeg','workflow_key':''} for n in [1,2,3] for i in [1,2]]
        return {'order_number':'8403','documents':docs,'assets':assets,'pdf_page_hashes':['old-version']}
    def test_three_documents_six_pages_preserve_names_and_page_counts(self):
        rows=images(self.sample());self.assertEqual(len(rows),6)
        self.assertEqual([r['document_id'] for r in rows],['order-3']*2+['order-2']*2+['order-1']*2)
        self.assertEqual([r['pdf_page_number'] for r in rows],[1,2]*3)
        self.assertTrue(all('/thumb/' in r['preview_url'] for r in rows))
    def test_pdf_disabled_hides_pages_and_document_names(self):
        order=self.sample();filter_assets_in_space({'orders':[order]},{'show_pdf_pages':False})
        self.assertEqual(images(order),[]);self.assertEqual(order['documents'],[])
    def test_old_pages_never_reappear_as_photos(self):
        order=self.sample();order['assets'].append({'asset_key':'old','sha256':'old-version','content_type':'image/jpeg'})
        filter_assets_in_space({'orders':[order]},{});self.assertEqual(len(images(order)),6)
    def test_source_visibility_and_other_workflow_do_not_leak(self):
        order=self.sample();order['documents'][0]['workflow_key']='1008403-1'
        for a in order['assets'][:2]:a['workflow_key']='1008403-1'
        rows=images(order,{'workflow_key':'1008403-2'})
        self.assertEqual(len(rows),4)
        filter_assets_in_space({'orders':[order]},{'show_images':False,'show_workflow_images':True})
        self.assertEqual(len(images(order,{'workflow_key':'1008403-1'})),2)
    def test_missing_page_does_not_invent_or_reassign_another_asset(self):
        order=self.sample();order['assets']=order['assets'][1:]
        rows=images(order);self.assertEqual(len(rows),5)
        self.assertNotIn(('order-1',1),[(r['document_id'],r['pdf_page_number']) for r in rows])
