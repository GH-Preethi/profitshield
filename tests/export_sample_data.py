"""Export isolated application data to stdout for Node tests; writes only to temp storage.

Usage: python3 tests/export_sample_data.py [samples|synthetic]
"""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.support import BackendCase, server


def export(mode):
    case = BackendCase()
    case.samples = mode == 'samples'
    try:
        with redirect_stdout(io.StringIO()):
            case.setUp()
            if mode == 'synthetic':
                for name in ['doordash_synthetic.csv', 'square_synthetic.csv', 'supplier_synthetic.csv']:
                    case.import_fixture(name)
            data = server.app_data()
        return data
    finally:
        case.doCleanups()


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'samples'
    if mode not in ('samples', 'synthetic'):
        raise SystemExit('Use samples or synthetic')
    print(json.dumps(export(mode), allow_nan=False))
