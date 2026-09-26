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
    assert (
        "- Tables that no `CREATE TABLE` statement in a string literal creates "
        "(created outside the code, by an ORM, or under a name built at run time)."
    ) in default.split("\n")
    custom_sql, _ = render_pair(tmp_path / "c", SHOP, "[sql]\ncreate = ['CREATE TABLE (\\w+)']\n")
    assert "Detector: custom SQL patterns from the configuration" in custom_sql
    assert (
        "- Tables that the configured `[sql] create` patterns do not match "
        "(created outside the code, by an ORM, or under a name built at run time)."
    ) in custom_sql.split("\n")
    assert "no `CREATE TABLE` statement" not in custom_sql


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


def section(arch, heading):
    """The lines of one section of the map, without the heading and the blank line that ends it."""
    return arch.split(f"## {heading}\n")[1].split("\n\n")[0].split("\n")


def hub_and_index_lines(tmp_path, doc, name="pipe"):
    files = {f"shop/{name}.py": f'"""{doc}"""\n', "shop/use.py": f"import shop.{name}\n"}
    arch, index = render_pair(tmp_path, files)
    hub = next(ln for ln in section(arch, "Most depended-on modules") if f"`shop.{name}`" in ln)
    return arch, index, hub, next(ln for ln in index.split("\n") if ln.startswith(f"shop.{name} | "))


def test_a_title_cut_at_its_width_never_leaves_trailing_whitespace(tmp_path):
    doc = "a" * 69 + " " + "b" * 19 + " " + "c" * 10  # the 70th and the 90th characters are spaces
    arch, index, hub, index_line = hub_and_index_lines(tmp_path, doc)
    assert hub == "- `shop.pipe` (1 importer) - " + "a" * 69
    assert index_line == "shop.pipe | " + "a" * 69 + " " + "b" * 19 + " | lib"
    for text in (arch, index):
        assert [ln for ln in text.split("\n") if ln != ln.rstrip()] == []


def test_a_pipe_in_an_index_title_is_written_as_a_slash_so_the_fields_stay_unambiguous(tmp_path):
    arch, index, hub, index_line = hub_and_index_lines(tmp_path, "Reads a | b and c|d")
    assert index_line == "shop.pipe | Reads a / b and c/d | lib"
    assert index_line.count(" | ") == 2  # key, title, role: nothing else in the line can split
    assert hub.endswith(" - Reads a | b and c|d")  # the map is not a delimited file, so its titles are left alone


def test_a_pipe_before_the_index_cut_does_not_move_the_cut(tmp_path):
    doc = "x|" * 60  # 120 characters, all kept up to the width
    _, _, _, index_line = hub_and_index_lines(tmp_path, doc)
    assert index_line == "shop.pipe | " + ("x/" * 45) + " | lib"


def test_the_closing_list_states_the_unparsable_file_caveat_whatever_the_config(tmp_path):
    caveat = (
        "- A file that cannot be decoded or parsed contributes its raw text (comments and docstrings included) as its "
        "only string literal, so SQL-looking text there can count as evidence for tables, their users and writers."
    )
    for name, toml in (("default", ""), ("custom", "[sql]\ncreate = ['CREATE TABLE (\\w+)']\n")):
        arch, _ = render_pair(tmp_path / name, SHOP, toml)
        closing = arch.split("## What this map cannot say\n")[1].split("\n")
        assert caveat in closing, name


def over_every_cap():
    """One repository that exceeds every cap of spec section 6.1 and 7.4. The counts are built in, not measured:
    27 packages (20 fillers and 7 real); 86 hubs (30 + 10 + 22 + 12 + 2 + 10) that all sit at depth 0; 12 import
    cycles (a ring of 10 and 11 pairs); 27 route files with one route group each; 27 tables, one of them written by 6
    library modules and read by 6 others; 23 look-alike names, one of them defined in 10 modules."""
    files = {f"pkg{i:02d}/m.py": "" for i in range(20)}
    files.update({f"hub/h{i:02d}.py": "" for i in range(30)})
    files["hub/user.py"] = "".join(f"import hub.h{i:02d}\n" for i in range(30))
    files.update({f"cyc/big{i:02d}.py": f"import cyc.big{(i + 1) % 10:02d}\n" for i in range(10)})
    for i in range(11):
        files[f"cyc/p{i:02d}_a.py"] = f"import cyc.p{i:02d}_b\n"
        files[f"cyc/p{i:02d}_b.py"] = f"import cyc.p{i:02d}_a\n"
    files.update({f"web/r{i:02d}.py": f'@app.route("/g{i:02d}/x")\ndef f():\n    pass\n' for i in range(27)})
    creates = ["CREATE TABLE orders (id INTEGER)"] + [f"CREATE TABLE t{i:02d} (id INTEGER)" for i in range(26)]
    files["db/schema.py"] = "tables = [\n" + "".join(f"    {c!r},\n" for c in creates) + "]\n"
    for i in range(6):
        files[f"svc/w{i}.py"] = 'sql = "INSERT INTO orders VALUES (1)"\n'
        files[f"svc/r{i}.py"] = 'sql = "SELECT * FROM orders"\n'
    files["svc/main.py"] = "".join(f"import svc.w{i}\nimport svc.r{i}\n" for i in range(6))
    same = "".join(f"class Dup{i:02d}:\n    pass\n\n\n" for i in range(22))
    files.update({"dup/a.py": same, "dup/b.py": same, "dup/main.py": "import dup.a\nimport dup.b\n"})
    files.update({f"wide/w{i:02d}.py": "class Wide:\n    pass\n" for i in range(10)})
    files["wide/main.py"] = "".join(f"import wide.w{i:02d}\n" for i in range(10))
    return files


def test_every_cap_prints_its_more_line_and_every_capped_name_list_its_plus_n_with_the_exact_n(tmp_path):
    arch, _ = render_pair(tmp_path, over_every_cap())

    packages = section(arch, "Packages")  # 27 packages, 25 shown
    assert len(packages) == 27 and packages[-2:] == ["- (+2 more packages)", "- top level - 0 modules"]

    layers = section(arch, "Dependency layers (computed from imports)")  # 6 modules named per depth
    assert layers[1:] == [
        "- depth 0 (86 modules): `cyc.big00`, `cyc.big01`, `cyc.big02`, `cyc.big03`, `cyc.big04`, `cyc.big05`, +80"
    ]

    cycles = section(arch, "Import cycles")  # 12 cycles, 10 shown, 8 names per cycle
    assert len(cycles) == 12
    assert cycles[1] == (
        "- `cyc.big00`, `cyc.big01`, `cyc.big02`, `cyc.big03`, `cyc.big04`, `cyc.big05`, `cyc.big06`, `cyc.big07`, "
        "+2 (10 modules)"
    )
    assert cycles[2] == "- `cyc.p00_a`, `cyc.p00_b` (2 modules)" and cycles[10] == "- `cyc.p08_a`, `cyc.p08_b` (2 modules)"
    assert cycles[-1] == "- (+2 more cycles)"

    hubs = section(arch, "Most depended-on modules")  # 86 hubs, 25 shown
    assert len(hubs) == 26 and hubs[-1] == "- (+61 more)"

    http = section(arch, "HTTP surface")  # 27 route files, 25 named; 27 route groups, 25 shown
    named = ", ".join(f"`web.r{i:02d}` (1)" for i in range(25))
    assert http[1] == f"27 routes in 27 files: {named}, +2."
    assert len(http) == 2 + 25 + 1 and http[-1] == "- (+2 more route groups)"

    database = section(arch, "Database")  # 27 tables, 25 shown; 4 writers and 4 readers named
    assert len(database) == 2 + 25 + 1 and database[-1] == "- (+2 more tables)"
    assert database[2] == (
        "- `orders` - 13 modules (12 library, 1 standalone); written by `svc.w0`, `svc.w1`, `svc.w2`, `svc.w3`, +3; "
        "also used by `svc.r0`, `svc.r1`, `svc.r2`, `svc.r3`, +2"
    )
    assert "- `t23` - 1 module (0 library, 1 standalone); written by `db.schema`" in database
    assert not any("`t24`" in ln for ln in database)

    same = section(arch, "Same name, different modules")  # 23 look-alike names, 20 shown, 8 names per line
    assert len(same) == 1 + 20 + 1 and same[-1] == "- (+3 more)"
    assert same[1] == (
        "- class `Wide`: `wide.w00`, `wide.w01`, `wide.w02`, `wide.w03`, `wide.w04`, `wide.w05`, `wide.w06`, `wide.w07`, +2"
    )
    assert same[2] == "- class `Dup00`: `dup.a`, `dup.b`" and same[-2] == "- class `Dup18`: `dup.a`, `dup.b`"
