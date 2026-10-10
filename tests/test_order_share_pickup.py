"""Exercise public ORDER cards and pickup rules without DB/network startup hooks."""
import ast
import copy
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import re
import runpy
import sys
import types
import unittest
from unittest.mock import patch
from urllib.parse import quote

from flask import Flask, Response, request
from jinja2 import FileSystemLoader


ROOT = Path(__file__).resolve().parents[1]


def functions(path, names, scope):
    tree = ast.parse((ROOT / path).read_text('utf-8'))
    body = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            node = copy.deepcopy(node)
            node.decorator_list = []
            body.append(node)
    assert len(body) == len(names)
    exec(compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])), path, 'exec'), scope)
    return scope


def native_scope():
    status_spec = importlib.util.spec_from_file_location('pickup_test_status', ROOT / 'order_tracking/status_definitions.py')
    status = importlib.util.module_from_spec(status_spec)
    status_spec.loader.exec_module(status)
    common = runpy.run_path(str(ROOT / 'order_tracking/share_common.py'))
    policy = runpy.run_path(str(ROOT / 'services/order_share_image_policy.py'))
    scope = dict(common, **policy)
    scope.update(copy=copy, datetime=datetime, timezone=timezone, quote=quote,
                 _status_module=lambda: status, _fingerprint=lambda: 'pickup-test',
                 TPL=ROOT / 'order_tracking/templates/tracking',
                 _STATIC_RE=re.compile(r"\{\{\s*url_for\(\s*['\"]tracking_bp\.static['\"]\s*,\s*filename\s*=\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}"),
                 _GUEST_RE=re.compile(r"\{\{\s*url_for\(\s*['\"]tracking_bp\.local_guest_customer['\"]\s*,\s*token\s*=\s*token\s*\)\s*\}\}"))
    return functions('services/order_share_native_order_ui.py', {
        '_key', '_label', '_pick', '_is_image', '_route', '_images',
        '_logistics_filter_key', '_logistics_filter_keys', '_fully_retired',
        '_card', '_cards', '_expiry', '_customer_context', '_source',
    }, scope)


def batch(container='MSCU1234567', pickup='picked_up', status='ARRIVED_IQUIQUE'):
    return dict(container_no=container, status=status, pickup_status=pickup,
                arrived_date='2026-10-01', eta_iquique='')


def order(status='COMPLETED', rows=None, number='1008000', workflows=1):
    return dict(order_number=number, order_status='ACTIVE', order_date='2026-10-01',
                logistics=[batch()] if rows is None else rows, assets=[],
                workflows=[dict(workflow_number=f'{number}-{i+1}', status=status,
                                last_status_change_date='2026-10-01', timeline=[])
                           for i in range(workflows)])


def render_orders(orders, mode='simple'):
    scope = native_scope()
    app = Flask('pickup-tests')
    app.jinja_loader = FileSystemLoader(str(ROOT / 'order_tracking/templates'))
    context = scope['_customer_context'](
        {'customer': {'customer_name': 'PRUEBA'}, 'orders': orders},
        {'status_filter_mode': mode}, 'test-token')
    with app.app_context():
        return app.jinja_env.from_string(scope['_source']('guest_customer.html')).render(**context)


class PickupCardsTests(unittest.TestCase):
    def setUp(self):
        self.scope = native_scope()

    def card(self, value):
        return self.scope['_cards']({'orders': [value]}, 'token')[0]

    def test_all_completed_and_all_batches_collected(self):
        value = order(rows=[batch(), batch('TGHU7654321')], workflows=2)
        cards = self.scope['_cards']({'orders': [value]}, 'token')
        self.assertEqual(len(cards), 2)
        for card in cards:
            self.assertTrue(card['is_retired'])
            self.assertEqual(card['current_status'], 'COMPLETED')
            self.assertEqual(card['display_status_key'], 'RETIRED')
            self.assertEqual(card['status_es'], 'Retirado')
            self.assertEqual(card['logistics_filter_keys'], [])
            self.assertEqual(card['logistics_filter'], 'none')
            self.assertFalse(card['partial_pickup'])

    def test_one_collected_batch_and_another_in_transit_is_active(self):
        card = self.card(order(rows=[batch(), batch('TGHU7654321', '', 'IN_TRANSIT')]))
        self.assertFalse(card['is_retired'])
        self.assertTrue(card['partial_pickup'])
        self.assertEqual(card['logistics_filter_keys'], ['in_transit'])

    def test_partially_picked_container_is_active(self):
        card = self.card(order(rows=[batch(), batch('TGHU7654321', 'pending_pickup')]))
        self.assertFalse(card['is_retired'])
        self.assertEqual(card['logistics_filter_keys'], ['pending_pickup'])

    def test_split_shipment_does_not_turn_gray_after_first_pickup(self):
        card = self.card(order(status='PARTIAL_SHIPPED'))
        self.assertFalse(card['is_retired'])
        self.assertTrue(card['partial_pickup'])

    def test_other_unfinished_workflow_keeps_completed_card_active(self):
        value = order(workflows=2)
        value['workflows'][1]['status'] = 'PRODUCING'
        for card in self.scope['_cards']({'orders': [value]}, 'token'):
            self.assertFalse(card['is_retired'])

    def test_all_shipped_without_completion_is_not_retired(self):
        self.assertFalse(self.card(order(status='ALL_SHIPPED'))['is_retired'])

    def test_partial_shipping_evidence_blocks_retirement(self):
        value = order()
        value['workflows'][0]['timeline'] = [{'status': 'PARTIAL_SHIPPED', 'action_date': '2026-10-01'}]
        self.assertFalse(self.card(value)['is_retired'])

    def test_partial_history_can_finish_with_all_shipped(self):
        value = order()
        value['workflows'][0]['timeline'] = [
            {'status': 'PARTIAL_SHIPPED', 'action_date': '2026-09-01'},
            {'status': 'ALL_SHIPPED', 'action_date': '2026-10-01'},
        ]
        self.assertTrue(self.card(value)['is_retired'])

    def test_unknown_logistics_never_implies_retirement(self):
        for rows in ([], [batch(pickup='')], [batch(container='')], [batch(status='UNKNOWN')], [batch(), None]):
            with self.subTest(rows=rows):
                self.assertFalse(self.card(order(rows=rows))['is_retired'])

    def test_mixed_batches_match_both_current_logistics_filters(self):
        card = self.card(order(rows=[batch(pickup='pending_pickup'), batch('TGHU7654321', '', 'IN_TRANSIT')]))
        self.assertEqual(card['logistics_filter_keys'], ['in_transit', 'pending_pickup'])

    def test_no_workflows_or_pickup_only_card_cannot_retire(self):
        self.assertFalse(self.card(order(workflows=0))['is_retired'])
        value = order()
        value['extra_pickup_only'] = True
        self.assertFalse(self.card(value)['is_retired'])

    def test_28_workflows_in_24_orders_still_count_as_28_cards(self):
        orders = [order(number=str(1008000+i), workflows=2 if i < 4 else 1) for i in range(24)]
        context = self.scope['_customer_context']({'orders': orders}, {}, 'token')
        self.assertEqual(len(context['orders']), 28)
        self.assertEqual(context['normal_card_count'], 28)
        self.assertEqual(context['logistics_counts']['all'], 0)
        self.assertEqual(set(context['logistics_counts']), {'all', 'in_transit', 'pending_pickup'})
        self.assertEqual(sum(card['is_retired'] for card in context['orders']), 28)

    def test_batch_count_does_not_inflate_workflow_count(self):
        context = self.scope['_customer_context']({'orders': [order(rows=[batch(pickup='pending_pickup')]*3)]}, {}, 'token')
        self.assertEqual(context['logistics_counts']['pending_pickup'], 1)

    def test_51_normal_workflows_and_extra_pickup_have_independent_totals(self):
        orders = [order(number=str(1008100+i), rows=[batch('', '', 'IN_TRANSIT')] if i < 13 else []) for i in range(51)]
        extra = order(number='1007000', rows=[batch(pickup='pending_pickup')], workflows=0)
        extra['extra_pickup_only'] = True
        orders.append(extra)
        context = self.scope['_customer_context']({'orders': orders}, {}, 'token')
        self.assertEqual(len(context['orders']), 52)
        self.assertEqual(context['normal_card_count'], 51)
        self.assertEqual(context['status_counts'], {'all': 51, 'unconfirmed': 0, 'confirmed': 0, 'done': 51, 'retired': 0})
        self.assertEqual(context['extra_pickup_count'], 1)
        self.assertEqual(context['logistics_counts'], {'all': 14, 'in_transit': 13, 'pending_pickup': 1})

    def test_logistics_union_deduplicates_mixed_batches_and_repeated_workflows(self):
        value = order(rows=[batch(pickup='pending_pickup'), batch('TGHU7654321', '', 'IN_TRANSIT')], workflows=2)
        context = self.scope['_customer_context']({'orders': [value, copy.deepcopy(value)]}, {}, 'token')
        self.assertEqual(context['normal_card_count'], 2)
        self.assertEqual(context['logistics_counts'], {'all': 2, 'in_transit': 2, 'pending_pickup': 2})

    def test_visible_order_replaces_stale_pickup_only_copy(self):
        value = order(rows=[batch(pickup='pending_pickup')])
        extra = copy.deepcopy(value)
        extra.update(workflows=[], extra_pickup_only=True)
        for orders in ([value, extra], [extra, value]):
            context = self.scope['_customer_context']({'orders': orders}, {}, 'token')
            self.assertEqual(len(context['orders']), 1)
            self.assertEqual(context['extra_pickup_count'], 0)

    def test_template_keeps_retired_card_clickable_and_images_available(self):
        value = order()
        value['assets'] = [{'asset_key': 'a'*64, 'asset_type': 'IMAGE', 'content_type': 'image/jpeg'}]
        html = render_orders([value])
        self.assertIn('guest-card guest-card-retired', html)
        self.assertIn('href="/share/test-token/order/1008000-1"', html)
        self.assertIn('/share/test-token/image/'+'a'*64, html)
        self.assertNotIn('guestLogisticsRetired', html)
        self.assertNotIn('data-guest-logistics-count="retired"', html)
        self.assertIn("{key:'retired', zh:'已取完', es:'Retirado'", html)

    def test_template_displays_each_batches_pickup_state(self):
        html = render_orders([order(rows=[batch(), batch('TGHU7654321', 'pending_pickup')])])
        self.assertIn('Retiro parcial', html)
        self.assertIn('Retirado · Iquique', html)
        self.assertIn('Llegó', html)
        self.assertNotIn('class="guest-card guest-card-retired"', html)

    def test_compatibility_response_keeps_pickup_groups_and_icons(self):
        scope = functions('services/order_share_visibility_live_patch.py', {'_inject_live_dom_patch'},
                          {'request': request, '_LIVE_PATCH_JS': ''})
        app = Flask('compatibility-test')
        with app.test_request_context('/share/test-token'):
            html = scope['_inject_live_dom_patch'](Response(render_orders([order()]), mimetype='text/html')).get_data(as_text=True)
        self.assertIn("return 'retired';", html)
        self.assertIn("return 'done';", html)
        self.assertNotIn("return 'ended';", html)


def frontend_samples():
    split = order('PARTIAL_SHIPPED', [batch(), batch('TGHU7654321', '', 'IN_TRANSIT')], '1009000')
    mixed = order(rows=[batch(pickup='pending_pickup'), batch('TGHU7654321', '', 'IN_TRANSIT')], number='1009001')
    retired = order(number='1009002')
    unknown = order(rows=[], number='1009003')
    unfinished = order(number='1009004', workflows=2)
    unfinished['workflows'][1]['status'] = 'PARTIAL_SHIPPED'
    quote_order = order('QUOTE_CONFIRMING', [], '1009005')
    for value, dates in [(split, ['2026-09-15']), (mixed, ['2026-10-02']),
                         (retired, ['2026-10-01']), (unfinished, ['2026-09-20', '2026-10-03'])]:
        for workflow, date in zip(value['workflows'], dates):
            workflow['timeline'] = [{'status': 'PARTIAL_SHIPPED' if workflow['status'] == 'PARTIAL_SHIPPED' else 'ALL_SHIPPED', 'action_date': date}]
    return [split, mixed, retired, unknown, unfinished, quote_order]


def write_frontend_fixtures(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    samples = frontend_samples()
    for name, orders, mode in [
        ('empty', [], 'simple'), ('sample', samples, 'simple'), ('full', samples, 'full'),
        ('all28', [order(number=str(1008000+i), workflows=2 if i < 4 else 1) for i in range(24)], 'simple'),
    ]:
        (destination / f'{name}.html').write_text(render_orders(orders, mode), 'utf-8')
    normals = [order(number=str(1008100+i), rows=[batch('', '', 'IN_TRANSIT')] if i < 13 else []) for i in range(51)]
    extra = order(number='1007000', rows=[batch(pickup='pending_pickup')], workflows=0)
    extra['extra_pickup_only'] = True
    (destination / '51-plus-pickup.html').write_text(render_orders(normals + [extra]), 'utf-8')


class RetentionTests(unittest.TestCase):
    def setUp(self):
        policy = runpy.run_path(str(ROOT / 'services/order_share_image_policy.py'))
        class Clock(datetime):
            @classmethod
            def utcnow(cls):
                return cls(2026, 10, 9, 12)
        self.scope = functions('services/order_public_share_fast.py',
            {'_scope', '_parse_dt', '_months_ago_first', '_wf_visible', '_filter_space'},
            dict(policy, datetime=Clock, _SCOPE_RANK={'current':0, '6m':1, '12m':2, 'all':3}))
        helpers = functions('services/order_cloud_service.py',
            {'_has_pending_pickup_logistics', '_prepare_extra_pickup_order'}, {})
        self.cloud = types.ModuleType('services.order_cloud_service')
        self.cloud.__dict__.update(helpers)

    def filtered(self, value, scope='current'):
        with patch.dict(sys.modules, {'services.order_cloud_service': self.cloud}):
            return self.scope['_filter_space']({'orders': [value]}, {'history_scope': scope})['orders']

    def test_retired_orders_remain_until_three_month_boundary(self):
        value = order()
        value['workflows'][0]['last_status_change_date'] = '2026-07-09'
        self.assertEqual(len(self.filtered(value)), 1)

    def test_retired_orders_age_out_only_after_scope_boundary(self):
        value = order()
        value['workflows'][0]['last_status_change_date'] = '2026-07-08'
        self.assertEqual(self.filtered(copy.deepcopy(value)), [])
        self.assertEqual(len(self.filtered(value, 'all')), 1)

    def test_unfinished_order_keeps_old_picked_batch(self):
        value = order(status='PARTIAL_SHIPPED')
        value['workflows'][0]['last_status_change_date'] = '2025-01-01'
        self.assertEqual(len(self.filtered(value)), 1)

    def test_existing_overdue_pending_pickup_exception_remains(self):
        value = order(rows=[batch(pickup='pending_pickup')])
        value['workflows'][0]['last_status_change_date'] = '2025-01-01'
        self.assertTrue(self.filtered(value)[0]['extra_pickup_only'])


if __name__ == '__main__':
    unittest.main()
