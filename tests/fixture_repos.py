"""Synthetic repositories used by the command-line tests. Invented names only."""

TINY = {
    "shop/__init__.py": '"""Shop package."""\n',
    "shop/ledger.py": '"""Ledger of money movements."""\nimport sqlite3\n\nSCHEMA = "CREATE TABLE ledger (id INTEGER)"\n',
    "shop/orders.py": '"""Order handling."""\nfrom shop import ledger\n',
    "scripts/report.py": '"""Print a report."""\nfrom shop import orders\n\nif __name__ == "__main__":\n    print(orders)\n',
}


PORTABLE = {
    "indextool.toml": 'title = "Portable shop"\nexclude = ["legacy/"]\n',
    "shop/__init__.py": '"""Shop package."""\n',
    "shop/ledger.py": (
        '"""Ledger of money movements."""\nimport sqlite3\n\nSCHEMA = "CREATE TABLE ledger (id INTEGER)"\n'
        'RATES = {"usd": 1}\n\n\nclass Money:\n    pass\n'
    ),
    "shop/orders.py": (
        '"""Order handling."""\nimport sqlite3\nfrom shop import ledger\n\nSQL = "CREATE TABLE orders (id INTEGER)"\n'
        'INSERT = "INSERT INTO orders VALUES (1)"\nRATES = {"eur": 2}\n\n\nclass Money:\n    pass\n'
    ),
    "shop/web.py": (
        '"""HTTP routes."""\nfrom flask import Flask\nfrom shop import orders\n\napp = Flask(__name__)\n\n\n'
        '@app.route("/orders")\ndef list_orders():\n    return orders\n\n\n'
        '@app.route("/orders/<int:id>")\ndef show(id):\n    return id\n'
    ),
    "shop/cycle_a.py": "from shop import cycle_b\n",
    "shop/cycle_b.py": "from shop import cycle_a\n",
    "shop/cafe.py": '"""Crème brûlée café."""\nimport requests\n',
    "shop/broken.py": "def broken(:\n",
    "scripts/report.py": '"""Print a report."""\nfrom shop import orders\n\nif __name__ == "__main__":\n    print(orders)\n',
    "tests/test_orders.py": "from shop import orders\n",
    "legacy/old.py": "from shop import orders\n",
}

LATIN1 = {"shop/legacy_names.py": b'# -*- coding: latin-1 -*-\n"""Caf\xe9 module."""\n'}

PEP701 = {"a.py": 'names = ["x"]\nmsg = f"{"\\n".join(names)}"\n'}
