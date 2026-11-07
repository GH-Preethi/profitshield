import json
import os
from pathlib import Path
import runpy
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch
import urllib.request

import server
from square_actions import ActionError, PlanStore
from square_fakes import FakeSquare
from test_http_security import HTTPFixture


def menu_request(channels=None):
    return {'week': '2026-10-26', 'channels': channels or ['In-store'],
            'changes': [{'sku': 'marg', 'old_price': 16, 'price': 16.75}]}


def confirmation(plan):
    payload = {'plan_id': plan['plan_id'], 'confirmation': plan['confirmation']}
    if plan['kind'] == 'menu':
        payload['week'] = plan['review']['week']
    return payload


class SquareGuardTests(HTTPFixture):
    def setUp(self):
        self.token_patch = patch.object(server, 'SQUARE_TOKEN', 'dummy-sandbox-token')
        self.token_patch.start()
        self.fake = FakeSquare()
        self.fake.add_item('Margherita pizza')
        self.transport_patch = patch.object(server.SQUARE_OPENER, 'open', side_effect=self.fake.open)
        self.transport_patch.start()
        with patch.object(server, 'KEY', ''):
            server.init_db()
        with server.db() as con:
            con.execute('DELETE FROM square_actions')
            con.execute('DELETE FROM menu_prices')
        self.addCleanup(self.token_patch.stop)
        self.addCleanup(self.transport_patch.stop)

    def preview(self):
        return server.preview_menu(menu_request())

    def test_production_environment_cannot_select_production_host(self):
        with patch.dict(os.environ, {'SQUARE_ENV': 'production', 'SQUARE_ACCESS_TOKEN': 'dummy-sandbox-token'}):
            loaded = runpy.run_path(str(Path(server.__file__)), run_name='sandbox_config_test')
        self.assertEqual(loaded['SQUARE_BASE'], 'https://connect.squareupsandbox.com')
        server.square_sync()
        self.assertTrue(self.fake.requests)
        self.assertFalse(self.fake.writes)

    def test_runtime_production_base_override_fails_before_transport(self):
        with patch.object(server, 'SQUARE_BASE', 'https://connect.squareup.com'), patch.object(
                server.SQUARE_OPENER, 'open') as transport:
            for call in [lambda: server.square('GET', '/v2/locations'), self.preview,
                         lambda: server.preview_seed({}), lambda: server.apply_menu({})]:
                with self.assertRaises(ActionError):
                    call()
            transport.assert_not_called()

    def test_redirects_and_arbitrary_endpoints_are_denied(self):
        redirect = server.NoSquareRedirect()
        request = urllib.request.Request('https://connect.squareupsandbox.com/v2/locations')
        for code in [301, 302, 303, 307, 308]:
            with self.subTest(code=code), self.assertRaises(ActionError):
                redirect.redirect_request(request, None, code, 'redirect', {}, 'https://connect.squareup.com/v2/locations')
        before = len(self.fake.requests)
        for path in ['https://connect.squareup.com/v2/orders', '//connect.squareup.com/v2/orders',
                     '/v2/orders?host=production', '/v2/../orders', '/v2/unknown']:
            with self.assertRaises(ActionError):
                server.square('POST', path, {})
        self.assertEqual(len(self.fake.requests), before)

    def test_direct_mutators_need_claimed_review(self):
        for call in [server.square_seed, lambda: server.square_set_price('Margherita pizza', 1675),
                     lambda: server.square('POST', '/v2/orders', {}),
                     lambda: server.square('POST', '/v2/catalog/object', {}),
                     lambda: server.apply_menu({'changes': [{'sku': 'marg', 'price': 17}]})]:
            with self.assertRaises(ActionError):
                call()
        self.assertFalse(self.fake.writes)

    def test_price_review_is_read_only_and_requires_exact_confirmation(self):
        plan = self.preview()
        self.assertFalse(self.fake.writes)
        self.assertEqual(plan['review']['environment'], 'sandbox')
        self.assertEqual(plan['review']['changes'][0]['new_price'], 16.75)
        for bad in [{}, {'plan_id': plan['plan_id']}, {**confirmation(plan), 'confirmation': 'yes'},
                    {**confirmation(plan), 'changes': [{'sku': 'marg', 'price': 999}]}]:
            with self.assertRaises(ActionError):
                server.apply_menu(bad)
        self.assertFalse(self.fake.writes)
        result = server.apply_menu(confirmation(plan))
        self.assertEqual(result['results'][0]['new_price'], 16.75)
        self.assertEqual(len(self.fake.writes), 1)
        self.assertEqual(self.fake.catalog['Margherita pizza']['item_variation_data']['price_money']['amount'], 1675)
        self.assertIn(plan['plan_id'], self.fake.writes[0][1])

    def test_replay_and_concurrent_confirmation_cannot_apply_twice(self):
        plan = self.preview()
        def execute(_):
            try:
                server.apply_menu(confirmation(plan))
                return 'completed'
            except ActionError:
                return 'rejected'
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(execute, range(4)))
        self.assertEqual(results.count('completed'), 1)
        self.assertEqual(len(self.fake.writes), 1)
        with patch.object(server, 'PLANS', PlanStore(server.db)), self.assertRaises(ActionError):
            server.apply_menu(confirmation(plan))
        self.assertEqual(len(self.fake.writes), 1)

    def test_two_reviews_of_same_simulation_cannot_apply_twice(self):
        first, second = self.preview(), self.preview()
        server.apply_menu(confirmation(first))
        with self.assertRaises(ActionError):
            server.apply_menu(confirmation(second))
        with self.assertRaises(ActionError):
            self.preview()  # old_price=16 is now stale even for a fresh preview request
        self.assertEqual(len(self.fake.writes), 1)

    def test_claim_survives_crash_before_first_write(self):
        plan = self.preview()
        server.PLANS.claim(confirmation(plan), 'menu', server.action_state)
        with patch.object(server, 'PLANS', PlanStore(server.db)), self.assertRaises(ActionError):
            server.apply_menu(confirmation(plan))
        self.assertFalse(self.fake.writes)

    def test_disconnected_plan_cannot_gain_a_new_square_connection(self):
        with patch.object(server, 'SQUARE_TOKEN', ''):
            plan = self.preview()
            self.assertFalse(plan['review']['connected'])
        with self.assertRaises(ActionError):
            server.apply_menu(confirmation(plan))
        self.assertFalse(self.fake.writes)

    def test_delivery_only_plan_never_calls_square(self):
        plan = server.preview_menu(menu_request(['DoorDash']))
        result = server.apply_menu(confirmation(plan))
        self.assertIn('manual', result['results'][0]['pushed']['DoorDash'])
        self.assertFalse(self.fake.requests)
        self.assertFalse(self.fake.writes)

    def test_expired_week_changed_and_local_data_changed_plans_rejected(self):
        expired = self.preview()
        with server.db() as con:
            con.execute('UPDATE square_actions SET created=0 WHERE id=?', (expired['plan_id'],))
        with self.assertRaises(ActionError):
            server.apply_menu(confirmation(expired))
        wrong_week = self.preview()
        with self.assertRaises(ActionError):
            server.apply_menu({**confirmation(wrong_week), 'week': '2026-10-19'})
        changed = self.preview()
        with server.db() as con:
            con.execute('UPDATE orders SET subtotal=subtotal+1 WHERE rowid=(SELECT MIN(rowid) FROM orders)')
        with self.assertRaises(ActionError):
            server.apply_menu(confirmation(changed))
        self.assertFalse(self.fake.writes)

    def test_remote_catalog_and_connection_changes_reject_stale_plan(self):
        plan = self.preview()
        self.fake.catalog['Margherita pizza']['version'] += 1
        with self.assertRaises(ActionError):
            server.apply_menu(confirmation(plan))
        self.assertFalse(self.fake.writes)
        with server.db() as con:
            self.assertEqual(con.execute('SELECT status FROM square_actions WHERE id=?', (plan['plan_id'],)).fetchone()[0], 'failed')
        other = self.preview()
        with patch.object(server, 'SQUARE_TOKEN', 'different-dummy-sandbox-token'), self.assertRaises(ActionError):
            server.apply_menu(confirmation(other))
        self.assertFalse(self.fake.writes)

    def test_all_catalog_targets_checked_before_first_write(self):
        self.fake.add_item('Pepperoni pizza', 1800)
        p = menu_request()
        p['changes'].append({'sku': 'pep', 'old_price': 18, 'price': 18.75})
        plan = server.preview_menu(p)
        self.fake.catalog['Pepperoni pizza']['version'] += 1
        with self.assertRaises(ActionError):
            server.apply_menu(confirmation(plan))
        self.assertFalse(self.fake.writes)

    def test_uncertain_provider_outcome_is_consumed_not_retried(self):
        plan = self.preview()
        self.fake.lose_next_write = True
        with self.assertRaises(ActionError) as uncertain:
            server.apply_menu(confirmation(plan))
        self.assertEqual(uncertain.exception.status, 502)
        with self.assertRaises(ActionError):
            server.apply_menu(confirmation(plan))
        self.assertEqual(len(self.fake.writes), 1)
        with server.db() as con:
            self.assertEqual(con.execute('SELECT status FROM square_actions WHERE id=?', (plan['plan_id'],)).fetchone()[0], 'failed')

    def test_seed_requires_review_and_creates_three_orders_once(self):
        status, _, _ = self.request('POST', '/api/square/seed', {})
        self.assertEqual(status, 400)
        plan = server.preview_seed({})
        self.assertFalse(self.fake.writes)
        self.assertEqual(len(plan['review']['baskets']), 3)
        result = server.confirm_seed(confirmation(plan))
        self.assertEqual(result['created'], 3)
        with self.assertRaises(ActionError):
            server.confirm_seed(confirmation(plan))
        self.assertEqual(len(self.fake.orders), 3)
        self.assertEqual(len(self.fake.writes), 3)
        self.assertEqual(len({w[1] for w in self.fake.writes}), 3)

    def test_seed_location_staleness_blocks_all_orders(self):
        plan = server.preview_seed({})
        self.fake.location['id'] = 'different-sandbox-location'
        with self.assertRaises(ActionError):
            server.confirm_seed(confirmation(plan))
        self.assertFalse(self.fake.writes)

    def test_missing_item_creation_is_reviewed_and_one_use(self):
        self.fake.catalog.clear()
        plan = self.preview()
        self.assertEqual(plan['review']['changes'][0]['target']['mode'], 'create')
        server.apply_menu(confirmation(plan))
        with self.assertRaises(ActionError):
            server.apply_menu(confirmation(plan))
        self.assertEqual(len(self.fake.catalog), 1)
        self.assertEqual(len(self.fake.writes), 1)

    def test_invalid_prices_or_ambiguous_catalog_cannot_mutate(self):
        for value in [float('nan'), float('inf'), True, 0, -1, 16, 16.755, 10**1000]:
            p = menu_request()
            p['changes'][0]['price'] = value
            with self.subTest(value=str(value)[:20]), self.assertRaises(ActionError):
                server.preview_menu(p)
        with patch.object(server, 'square', return_value={'objects': [{}, {}]}), self.assertRaises(ActionError):
            self.preview()
        self.assertFalse(self.fake.writes)

    def test_http_origin_type_and_confirmation_contract(self):
        for path in ['/api/menu/preview', '/api/menu/apply', '/api/square/seed/preview', '/api/square/seed']:
            self.assertEqual(self.request('POST', path, {}, headers={'Origin': 'https://attacker.test'})[0], 403)
            self.assertEqual(self.request('POST', path, {}, headers={'Content-Type': 'text/plain'})[0], 415)
        status, _, body = self.request('POST', '/api/menu/preview', menu_request())
        self.assertEqual(status, 200)
        plan = json.loads(body)
        self.assertEqual(self.request('POST', '/api/menu/apply', confirmation(plan))[0], 200)
        self.assertEqual(self.request('POST', '/api/menu/apply', confirmation(plan))[0], 409)
        self.assertEqual(len(self.fake.writes), 1)

    def test_ui_contains_no_global_execution_or_chat_mutation(self):
        source = self.dashboard
        self.assertNotIn('LAST_SIM', source)
        self.assertNotIn('executeSim', source)
        self.assertIn('Chat commands cannot execute changes', source)
        self.assertIn('Review sandbox changes', source)
