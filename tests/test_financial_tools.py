import json
from tests.support import BackendCase, FIXTURES, server


class SyntheticFinancialTests(BackendCase):
    def setUp(self):
        super().setUp()
        for name in ['doordash_synthetic.csv', 'square_synthetic.csv', 'supplier_synthetic.csv']:
            self.import_fixture(name)
        self.context = {'week': '2026-10-26', 'prev_week': '2026-10-19', 'facts': {}}

    def test_commission_contract_difference_and_promo_cost(self):
        commission = server.tool_check_commissions(self.context)
        self.assertEqual(commission['overcharged_orders'], 1)
        self.assertAlmostEqual(commission['total_overcharge'], 1.6)
        self.assertEqual(server.tool_check_commissions(self.context, channel='Uber Eats')['overcharged_orders'], 0)
        promo = server.tool_find_unapproved_promos(self.context)['promotions'][0]
        self.assertEqual((promo['cost'], promo['approved']), (2, False))

    def test_price_changes_and_duplicate_document_dedupe(self):
        changes = server.tool_find_price_changes(self.context)['changes']
        self.assertEqual(changes[0]['ingredient'], 'Mozzarella')
        self.assertEqual((changes[0]['last_week'], changes[0]['this_week'], changes[0]['change_pct']), (4.1, 5.6, 36.6))
        with server.db() as con:
            con.execute("INSERT INTO invoice_lines SELECT invoice_number,vendor,date,'Second document',line,description,"
                        "ingredient,qty,unit,unit_price,total,ai,page FROM invoice_lines WHERE invoice_number='FIXTURE-NEW'")
            prices = server._prices(con, self.context['week'])
        self.assertAlmostEqual(prices['mozz'][0], 5.6)
        documents = server.tool_find_duplicate_invoices(self.context)['duplicates']
        self.assertEqual(documents[0]['copies'], 2)
        self.assertEqual(documents[0]['amount'], 56)
        # This verifies document grouping only, not evidence of duplicate payment.

    def test_error_aggregation_and_price_simulation(self):
        errors = server.tool_error_charge_pattern(self.context)
        self.assertEqual((errors['charges'], errors['total'], errors['fri_sat_6_to_9pm']), (1, 1, 1))
        simulation = server.tool_simulate_price_change(self.context, items=['marg'], increase=.75, channels=['DoorDash'])
        self.assertEqual(simulation['units_sold_last_week'], {'DoorDash': 2})
        self.assertAlmostEqual(simulation['extra_profit_per_week'], 1.2)
        self.assertIn('no demand drop', simulation['assumes'])


class AuditedFinancialBaselines(BackendCase):
    samples = True

    def test_sample_financial_tool_baselines(self):
        audit = json.loads((FIXTURES / 'audit_baselines.json').read_text())
        expected = audit['imported']
        ctx = {'week': audit['week'], 'prev_week': audit['previous_week'], 'facts': {}}
        commission = server.tool_check_commissions(ctx)
        self.assertEqual(commission['overcharged_orders'], expected['commission_orders'])
        self.assertAlmostEqual(commission['total_overcharge'], expected['commission_overcharge'])
        promo = next(p for p in server.tool_find_unapproved_promos(ctx)['promotions'] if not p['approved'])
        self.assertEqual((promo['orders'], promo['cost']), (expected['unapproved_promo_orders'], expected['unapproved_promo_cost']))
        documents = server.tool_find_duplicate_invoices(ctx)['duplicates']
        self.assertEqual(documents[0]['amount'], expected['duplicate_document_amount'])
        errors = server.tool_error_charge_pattern(ctx)
        self.assertEqual((errors['charges'], errors['total']), (expected['error_charge_count'], expected['error_charge_total']))
        simulation = server.tool_simulate_price_change(ctx, increase=.5)
        self.assertEqual(simulation['units_sold_last_week'], expected['pizza_units'])
        self.assertAlmostEqual(simulation['extra_profit_per_week'], expected['pizza_50_cent_simulation'])
        self.network.assert_not_called()
