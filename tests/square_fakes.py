"""In-memory Square sandbox transport. Never makes network calls."""
import copy
import io
import json
from urllib.parse import urlsplit
import urllib.error


class FakeSquare:
    def __init__(self):
        self.requests = []
        self.catalog = {}
        self.orders = []
        self.idempotency = {}
        self.writes = []
        self.location = {'id': 'sandbox-location', 'name': 'Sandbox test restaurant'}
        self.lose_next_write = False

    def add_item(self, name, price=1600):
        self.catalog[name] = {'type': 'ITEM_VARIATION', 'id': 'variation-'+str(len(self.catalog)+1), 'version': 1,
                              'item_variation_data': {'name': 'Regular', 'pricing_type': 'FIXED_PRICING',
                               'price_money': {'amount': price, 'currency': 'USD'}}}

    def open(self, request, timeout=30):
        url = urlsplit(request.full_url)
        assert url.scheme == 'https' and url.netloc == 'connect.squareupsandbox.com', request.full_url
        method, path = request.get_method(), url.path
        body = json.loads(request.data) if request.data else None
        self.requests.append((method, path, copy.deepcopy(body)))
        if path == '/v2/locations':
            response = {'locations': [self.location]}
        elif path == '/v2/catalog/search':
            name = body['query']['exact_query']['attribute_value']
            response = {'objects': [{'id': 'item-'+name, 'type': 'ITEM', 'item_data': {
                'name': name, 'variations': [self.catalog[name]]}}]} if name in self.catalog else {}
        elif path == '/v2/orders/search':
            response = {'orders': self.orders}
        elif path in ('/v2/orders', '/v2/catalog/object'):
            key = body['idempotency_key']
            if key in self.idempotency:
                return io.BytesIO(json.dumps(self.idempotency[key]).encode())
            if path == '/v2/orders':
                order = copy.deepcopy(body['order'])
                order.update({'id': f'{len(self.orders)+1:08d}', 'created_at': '2026-10-30T16:00:00Z'})
                self.orders.append(order)
                response = {'order': order}
            else:
                obj = copy.deepcopy(body['object'])
                if obj['type'] == 'ITEM':
                    name = obj['item_data']['name']
                    self.add_item(name, obj['item_data']['variations'][0]['item_variation_data']['price_money']['amount'])
                else:
                    name = next(name for name, old in self.catalog.items() if old['id'] == obj['id'])
                    if obj['version'] != self.catalog[name]['version']:
                        raise AssertionError('Catalog version conflict')
                    obj['version'] += 1
                    self.catalog[name] = obj
                response = {'catalog_object': self.catalog[name]}
            self.writes.append((path, key, copy.deepcopy(body)))
            self.idempotency[key] = copy.deepcopy(response)
            if self.lose_next_write:
                self.lose_next_write = False
                raise urllib.error.URLError('mock lost response after sandbox accepted write')
        else:
            raise AssertionError('Unexpected endpoint: '+path)
        return io.BytesIO(json.dumps(response).encode())
