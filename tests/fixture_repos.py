"""Synthetic repositories used by the command-line tests. Invented names only."""

TINY = {
    "shop/__init__.py": '"""Shop package."""\n',
    "shop/ledger.py": '"""Ledger of money movements."""\nimport sqlite3\n\nSCHEMA = "CREATE TABLE ledger (id INTEGER)"\n',
    "shop/orders.py": '"""Order handling."""\nfrom shop import ledger\n',
    "scripts/report.py": '"""Print a report."""\nfrom shop import orders\n\nif __name__ == "__main__":\n    print(orders)\n',
}
