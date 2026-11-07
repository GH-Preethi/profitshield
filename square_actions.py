"""Durable, one-use review plans for sandbox-only mutations."""
from contextlib import contextmanager
import hashlib
import json
import secrets
import time


class ActionError(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


CONFIRMATIONS = {'menu': 'APPLY SANDBOX PRICES', 'seed': 'CREATE 3 SANDBOX ORDERS'}
PLAN_SECONDS = 300


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()).hexdigest()


class PlanStore:
    def __init__(self, connect):
        self.connect = connect

    @contextmanager
    def connection(self):
        con = self.connect()
        try:
            with con:
                yield con
        finally:
            con.close()

    def create(self, kind, review, state):
        identifier = secrets.token_urlsafe(32)
        now = time.time()
        with self.connection() as con:
            con.execute('INSERT INTO square_actions VALUES(?,?,?,?,?,?,?)',
                        (identifier, kind, json.dumps(review, allow_nan=False), state, now, 'pending', None))
        return {'plan_id': identifier, 'kind': kind, 'review': review,
                'confirmation': CONFIRMATIONS[kind], 'expires_at': now + PLAN_SECONDS}

    def claim(self, payload, kind, state):
        allowed = {'plan_id', 'confirmation'} | ({'week'} if kind == 'menu' else set())
        if not isinstance(payload, dict) or set(payload) != allowed:
            raise ActionError('Submit only the reviewed plan, confirmation phrase and selected week', 400)
        if not isinstance(payload['plan_id'], str) or len(payload['plan_id']) != 43:
            raise ActionError('Invalid plan id', 400)
        if payload['confirmation'] != CONFIRMATIONS[kind]:
            raise ActionError('Explicit confirmation phrase required', 400)
        with self.connection() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT * FROM square_actions WHERE id=?', (payload['plan_id'],)).fetchone()
            if not row or row['kind'] != kind or row['status'] != 'pending':
                raise ActionError('Plan is unknown, already submitted or no longer executable')
            now = time.time()
            if now < row['created'] or now >= row['created'] + PLAN_SECONDS:
                raise ActionError('Plan expired; review a new plan')
            review = json.loads(row['review'])
            if kind == 'menu' and payload['week'] != review['week']:
                raise ActionError('Selected week changed; review a new plan')
            if row['snapshot'] != state(con):
                raise ActionError('Restaurant data or connection changed; review a new plan')
            # Commit the claim BEFORE any external mutation. Crashes and ambiguous
            # provider outcomes never make this plan eligible for automatic retry.
            con.execute("UPDATE square_actions SET status='executing' WHERE id=?", (row['id'],))
        return {'id': row['id'], 'kind': kind, 'review': review}

    def finish(self, plan, status, result=None):
        with self.connection() as con:
            con.execute('UPDATE square_actions SET status=?,result=? WHERE id=?',
                        (status, json.dumps(result, allow_nan=False) if result is not None else None, plan['id']))
