from indextool import FORMAT_VERSION
from indextool.facts import derive_facts
from indextool.render import render_architecture, render_index
from indextool.scan import resolve_edges, scan
from tests.helpers import make_config

SHOP = {
    "shop/__init__.py": '"""Shop package."""\n',
    "shop/ledger.py": (
        '"""Ledger of money movements."""\nimport sqlite3\n\nSCHEMA = "CREATE TABLE ledger (id INTEGER)"\n\n\n'
        "class Money:\n    pass\n"
    ),
    "shop/orders.py": (
        '"""Order handling."""\nimport sqlite3\nfrom shop import ledger\n\nSQL = "CREATE TABLE orders (id INTEGER)"\n'
        'INSERT = "INSERT INTO orders VALUES (1)"\n\n\nclass Money:\n    pass\n'
    ),
    "shop/web.py": (
        '"""HTTP routes."""\nfrom flask import Flask\nfrom shop import orders\n\napp = Flask(__name__)\n\n\n'
        '@app.route("/orders")\ndef list_orders():\n    return orders\n\n\n'
        '@app.route("/orders/<int:id>")\ndef show(id):\n    return id\n'
    ),
    "shop/cycle_a.py": "from shop import cycle_b\n",
    "shop/cycle_b.py": "from shop import cycle_a\n",
    "scripts/report.py": '"""Print a report."""\nfrom shop import orders\n\nif __name__ == "__main__":\n    print(orders)\n',
    "tests/test_orders.py": "from shop import orders\n",
}


def render_pair(directory, files, toml="", excluded=0):
    cfg = make_config(directory, toml)
    mods = scan({p: c.encode("utf-8") for p, c in files.items()}, cfg)
    resolve_edges(mods)
    facts = derive_facts(mods, cfg)
    return render_architecture(mods, facts, cfg, excluded), render_index(mods, facts, cfg)


def test_header_and_numbers(tmp_path):
    arch, _ = render_pair(tmp_path, SHOP)
    lines = arch.split("\n")
    assert lines[0] == "# Architecture map"
    assert f"indextool {FORMAT_VERSION}" in "\n".join(lines[:3])
    assert "- 7 modules (plus 1 test module) in 2 packages; 1 with a `__main__` guard" in lines
    assert "- 5 are imported by another module; 2 standalone (imported by nothing: scripts, servers, entry points)" in lines
    assert "- 2 routes in 1 file; 2 tables created in code" in lines


def test_title_from_config(tmp_path):
    arch, _ = render_pair(tmp_path, SHOP, 'title = "Acme shop"\n')
    assert arch.split("\n")[0] == "# Architecture map: Acme shop"


def test_packages_layers_cycles_hubs_and_lookalikes(tmp_path):
    arch, _ = render_pair(tmp_path, SHOP)
    lines = arch.split("\n")
    assert "- `scripts` - 1 module" in lines and "- `shop` - 5 modules" in lines and "- top level - 1 module" in lines
    assert "- depth 0 (2 modules): `shop`, `shop.ledger`" in lines
    assert "- depth 1 (3 modules): `shop.orders`, `shop.cycle_a`, `shop.cycle_b`" in lines
    assert "- `shop.cycle_a`, `shop.cycle_b` (2 modules)" in lines
    assert "- `shop` (5 importers) - Shop package." in lines
    assert "- class `Money`: `shop.ledger`, `shop.orders`" in lines


def test_http_surface_and_database(tmp_path):
    arch, _ = render_pair(tmp_path, SHOP)
    lines = arch.split("\n")
    assert "2 routes in 1 file: `shop.web` (2)." in lines
    assert "- `/orders` - 1 route" in lines and "- `/orders/<int:id>` - 1 route" in lines
    assert "- `ledger` - 1 module (1 library, 0 standalone); written by `shop.ledger`" in lines
    assert "- `orders` - 1 module (1 library, 0 standalone); written by `shop.orders`" in lines


def test_index_lines(tmp_path):
    _, index = render_pair(tmp_path, SHOP)
    lines = index.split("\n")
    assert lines[0].startswith(f"# indextool {FORMAT_VERSION} index, one line per module")
    assert lines[1:] == [
        "scripts.report | Print a report. | standalone",
        "shop | Shop package. | lib",
        "shop.cycle_a | - | lib",
        "shop.cycle_b | - | lib",
        "shop.ledger | Ledger of money movements. | lib db-rw | tables: ledger*",
        "shop.orders | Order handling. | lib db-rw | tables: orders*",
        "shop.web | HTTP routes. | standalone http | routes 2",
    ]


def test_lists_are_capped_with_a_more_line(tmp_path):
    files = {f"t/hub{i:02d}.py": "" for i in range(30)}
    files["t/user.py"] = "".join(f"import t.hub{i:02d}\n" for i in range(30))
    arch, _ = render_pair(tmp_path, files)
    hubs = arch.split("## Most depended-on modules\n")[1].split("\n\n")[0].split("\n")
    assert len(hubs) == 26 and hubs[-1] == "- (+5 more)"


def test_an_empty_repository_renders_a_valid_map(tmp_path):
    arch, index = render_pair(tmp_path, {})
    assert "- 0 modules (plus 0 test modules) in 0 packages; 0 with a `__main__` guard" in arch
    assert arch.count("None found by this detector.") == 2
    assert index.split("\n") == [index.split("\n")[0]]


def test_detector_lines_and_cannot_say_reflect_the_config(tmp_path):
    custom, _ = render_pair(tmp_path / "a", SHOP, '[routes]\ndecorators = ["route"]\n')
    assert "Detector: functions decorated with `.route(...)`" in custom
    assert "Routes not registered by a decorator named `route`" in custom
    default, _ = render_pair(tmp_path / "b", SHOP)
    assert "`.route(...)`, `.get(...)`" in default
    assert "Detector: `CREATE TABLE` statements" in default
    custom_sql, _ = render_pair(tmp_path / "c", SHOP, "[sql]\ncreate = ['CREATE TABLE (\\w+)']\n")
    assert "Detector: custom SQL patterns from the configuration" in custom_sql


def test_counts_of_excluded_and_unparsable_files_are_printed(tmp_path):
    arch, _ = render_pair(tmp_path / "with", {"a.py": "x = 1\n", "b.py": "def broken(:\n"}, 'exclude = ["legacy/"]\n', excluded=3)
    assert "- 3 files excluded by the configured `exclude` patterns" in arch
    assert "- 1 file could not be parsed (counted as a module with no imports)" in arch
    plain, _ = render_pair(tmp_path / "plain", {"a.py": "x = 1\n"})
    assert "excluded by the configured" not in plain and "could not be parsed" not in plain


def test_output_does_not_depend_on_input_order(tmp_path):
    first = render_pair(tmp_path / "a", SHOP)
    second = render_pair(tmp_path / "b", dict(reversed(list(SHOP.items()))))
    assert first == second
