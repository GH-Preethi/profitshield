import json
from unittest.mock import patch
from tests.support import BackendCase, FIXTURES, server


class ImportTests(BackendCase):
    def test_known_formats_and_reimport_are_idempotent(self):
        for name, rows, kind in [('doordash_synthetic.csv', 2, 'payout'),
                                 ('square_synthetic.csv', 2, 'pos'), ('supplier_synthetic.csv', 2, 'invoice')]:
            with self.subTest(name=name):
                first = self.import_fixture(name)
                self.assertEqual((first['new_rows'], first['kind'], first['mapped_by']), (rows, kind, 'known format'))
                repeated = self.import_fixture(name)
                self.assertEqual(repeated['new_rows'], 0)
                self.assertEqual(repeated['duplicates_skipped'], rows)
        data = server.app_data()
        self.assertEqual((len(data['orders']), len(data['errors']), len(data['invoices'])), (4, 1, 2))
        current = next(o for o in data['orders'] if o['id'] == 'SYNTH-NEW')
        self.assertEqual(current['items'][0]['sku'], 'marg')
        self.assertEqual(current['items'][0]['qty'], 2)
        self.assertEqual(current['commission'], 8)
        self.network.assert_not_called()

    def test_unfamiliar_format_rules_and_synthetic_pii(self):
        result = self.import_fixture('grubhub_synthetic_unusual.csv')
        self.assertEqual((result['mapped_by'], result['new_rows'], result['redacted']), ('rules', 1, 2))
        self.assertEqual(set(result['removed_columns']), {'Customer Name', 'Customer Phone'})
        encoded = json.dumps(server.app_data())
        self.assertNotIn('Synthetic Guest', encoded)
        self.assertNotIn('2025550100', encoded)
        self.network.assert_not_called()

    def test_mixed_text_redaction_does_not_drop_financial_columns(self):
        headers, rows, count, removed = server.redact(
            ['Order ID', 'Customer Email', 'Note', 'Subtotal'],
            [{'Order ID': 'SYNTH-1', 'Customer Email': 'guest@example.invalid',
              'Note': 'Contact fixture@example.invalid or 202-555-0100', 'Subtotal': '16.00'}])
        self.assertIn('Subtotal', headers)
        self.assertEqual(rows[0]['Subtotal'], '16.00')
        self.assertEqual(rows[0]['Note'], 'Contact [email] or [phone]')
        self.assertEqual(count, 2)
        self.assertEqual(removed, ['Customer Email'])

    def test_dates_times_currency_and_learned_mapping(self):
        self.assertEqual(server.num('($1,234.50)'), -1234.5)
        self.assertEqual(server.parse_date('10/30/2026'), '2026-10-30')
        self.assertEqual(server.parse_time('7:30 PM'), '19:30')
        with server.db() as con:
            con.execute('INSERT INTO item_map VALUES(?,?)', ('fixture pie', 'marg'))
            self.assertEqual(server.parse_items(con, '2x Fixture pie; 1x Soda (2 L)')[0]['sku'], 'marg')
            self.assertEqual(server.parse_items(con, '2x Fixture pie')[0]['qty'], 2)

    def test_import_failure_rolls_back_prior_rows(self):
        # Malformed supplier line is a failure on the audited code and should
        # roll back the preceding valid line, not leave a half-import.
        text = (FIXTURES / 'supplier_synthetic.csv').read_text()
        lines = text.splitlines()
        bad = lines[-1].split(',')
        bad[4] = 'Infinity'
        with self.assertRaises((ValueError, OverflowError)):
            server.import_csv('\n'.join(lines[:-1]+[','.join(bad)]), 'supplier.csv', allow_ai=False)
        with server.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM invoice_lines').fetchone()[0], 0)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM imports').fetchone()[0], 0)


class SampleBaselineTests(BackendCase):
    samples = True

    def test_audited_sample_counts_and_deduplication(self):
        baseline = json.loads((FIXTURES / 'audit_baselines.json').read_text())
        data = server.app_data()
        for name, count in baseline['sample_counts'].items():
            self.assertEqual(len(data[name]), count, name)
        for prefix, count in baseline['sample_import_rows'].items():
            record = next(i for i in data['imports'] if i['file'].startswith(prefix))
            self.assertEqual(record['new_rows'], count)
        unusual = server.SAMPLES / 'grubhub_export_unusual_columns.csv'
        result = server.import_csv(unusual.read_text(encoding='utf-8-sig'), unusual.name, allow_ai=False)
        self.assertEqual((result['new_rows'], result['duplicates_skipped'], result['redacted']), (0, 50, 100))
        self.assertEqual(len(server.app_data()['orders']), 1776)
        self.network.assert_not_called()
