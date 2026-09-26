import pytest

from indextool.errors import ConfigError
from indextool.facts import derive_facts
from indextool.scan import resolve_edges, scan
from tests.helpers import make_config


def facts_of(directory, files, toml=""):
    cfg = make_config(directory, toml)
    mods = scan({p: c.encode("utf-8") for p, c in files.items()}, cfg)
    resolve_edges(mods)
    return derive_facts(mods, cfg)


SQL_APP = {
    "shop/ledger.py": 'import sqlite3\nSCHEMA = "CREATE TABLE IF NOT EXISTS ledger (id INTEGER)"\nq = "SELECT * FROM ledger"\n',
    "shop/orders.py": (
        'import sqlite3\nA = "CREATE TABLE orders (id INTEGER)"\nB = "INSERT INTO orders VALUES (1)"\n'
        'C = "SELECT o.id FROM orders o JOIN ledger l ON 1"\n'
    ),
    "shop/report.py": 'import sqlite3\nD = "SELECT * FROM orders"\n',
}


def test_created_tables_users_and_writers(tmp_path):
    facts = facts_of(tmp_path, SQL_APP)
    assert facts.created == {"ledger", "orders"}
    assert facts.tables == {
        "ledger": {"shop.ledger", "shop.orders"},
        "orders": {"shop.orders", "shop.report"},
    }
    assert facts.writers == {"ledger": {"shop.ledger"}, "orders": {"shop.orders"}}


def test_docstrings_and_comments_are_not_evidence_and_fstrings_count(tmp_path):
    files = {
        "a.py": 'X = "CREATE TABLE real_one (id INTEGER)"\n',
        "b.py": '"""Reads FROM real_one in prose."""\n# INSERT INTO real_one is a comment\n',
        "c.py": 'def f(t):\n    return f"INSERT INTO real_one VALUES ({t})"\n',
    }
    facts = facts_of(tmp_path, files)
    assert facts.tables == {"real_one": {"a", "c"}}
    assert facts.writers == {"real_one": {"a", "c"}}


def test_an_unparsable_file_contributes_its_raw_text_so_sql_in_a_comment_or_docstring_counts(tmp_path):
    files = {
        "a.py": 'X = "CREATE TABLE real_one (id INTEGER)"\n',
        "broken.py": "def broken(:\n# CREATE TABLE ghost (id INTEGER)\n'''INSERT INTO real_one VALUES (1)'''\n",
    }
    facts = facts_of(tmp_path, files)
    assert facts.created == {"real_one", "ghost"}
    assert facts.writers == {"real_one": {"a", "broken"}, "ghost": {"broken"}}
    assert facts.io["broken"] == ""


def test_similar_table_names_are_not_confused(tmp_path):
    files = {
        "a.py": 'A = "CREATE TABLE orders (id INT)"\nB = "CREATE TABLE orders_archive (id INT)"\nC = "INSERT INTO orders_archive VALUES (1)"\n',
        "b.py": 'D = "SELECT * FROM orders"\n',
    }
    facts = facts_of(tmp_path, files)
    assert facts.tables["orders"] == {"a", "b"} and facts.tables["orders_archive"] == {"a"}
    assert facts.writers["orders_archive"] == {"a"}


def test_test_modules_contribute_nothing(tmp_path):
    files = {
        "a.py": 'X = "CREATE TABLE t1 (id INTEGER)"\n',
        "test_a.py": 'X = "CREATE TABLE t2 (id INTEGER)"\n@app.route("/x")\ndef f(): pass\n',
    }
    facts = facts_of(tmp_path, files)
    assert facts.created == {"t1"} and facts.routes == {}
    assert "test_a" not in facts.io


def test_an_unparsable_test_module_contributes_nothing(tmp_path):
    files = {
        "a.py": 'X = "CREATE TABLE t1 (id INTEGER)"\n',
        "test_broken.py": "def broken(:\n# CREATE TABLE ghost (id INTEGER)\n'''INSERT INTO t1 VALUES (1)'''\n",
    }
    facts = facts_of(tmp_path, files)
    assert facts.created == {"t1"} and facts.writers == {"t1": {"a"}} and facts.routes == {}
    assert "test_broken" not in facts.io


def test_custom_create_pattern_and_table_names_are_escaped(tmp_path):
    toml = r"""
[sql]
create = ['DEFINE\s+"([\w$-]+)"']
"""
    files = {"a.py": "X = 'DEFINE \"my-table$1\"'\nY = 'INSERT INTO my-table$1 VALUES (1)'\n"}
    facts = facts_of(tmp_path, files, toml)
    assert facts.created == {"my-table$1"}
    assert facts.writers == {"my-table$1": {"a"}}


def test_routes_are_collected_per_module(tmp_path):
    files = {"web.py": "@app.route('/a')\ndef a(): pass\n@app.route('/b')\ndef b(): pass\n", "x.py": ""}
    assert facts_of(tmp_path, files).routes == {"web": ["/a", "/b"]}


@pytest.mark.parametrize(
    "source,expected",
    [
        ("import sqlite3\nq = 'SELECT 1'\n", "db-r"),
        ("import sqlite3\nq = 'INSERT INTO t VALUES (1)'\n", "db-rw"),
        ("import sqlite3\nq = f'UPDATE {t} SET a = 1'\n", "db-rw"),
        ("import sqlalchemy\ndf.to_sql('t', con)\n", "db-rw"),
        ("import requests\n", "network"),
        ("import urllib.parse\n", ""),
        ("from urllib import parse\n", ""),
        ("from urllib import request\n", "network"),
        ("import urllib.request\n", "network"),
        ("from urllib.request import urlopen\n", "network"),
        ("import flask\n", "http"),
        ("import sqlite3, requests\nfrom flask import Flask\n", "db-r+network+http"),
        ("q = 'INSERT INTO t VALUES (1)'\n", ""),
        ("from . import sqlite3\n", ""),
        ("import sqlite3\ndef broken(:\n", ""),
    ],
)
def test_io_rating(tmp_path, source, expected):
    assert facts_of(tmp_path, {"m.py": source}).io["m"] == expected


def test_io_lists_are_replaced_per_kind_by_config(tmp_path):
    toml = '[io]\nnetwork = ["mylib"]\n'
    facts = facts_of(tmp_path, {"a.py": "import mylib\n", "b.py": "import requests\n", "c.py": "import sqlite3\n"}, toml)
    assert (facts.io["a"], facts.io["b"], facts.io["c"]) == ("network", "", "db-r")


# Config validates a `use`/`write` template with a dummy word standing for @TABLES@. Real table names can make the
# substituted pattern fail to compile, and that must surface as a ConfigError naming the pattern, never a raw re.error.
TWO_TABLES = {"a.py": 'X = "CREATE TABLE orders (id INT)"\nY = "CREATE TABLE ledger_book (id INT)"\nZ = "x"\n'}


@pytest.mark.parametrize("key", ["use", "write"])
def test_template_that_fails_with_real_table_names_is_a_config_error(tmp_path, key):
    template = "(?<=(@TABLES@))x"  # compiles with one word, but a look-behind needs one fixed width
    cfg = make_config(tmp_path, f"[sql]\n{key} = ['{template}']\n")
    mods = scan({p: c.encode("utf-8") for p, c in TWO_TABLES.items()}, cfg)
    with pytest.raises(ConfigError) as info:
        derive_facts(mods, cfg)
    assert f"[sql] {key}" in str(info.value) and template in str(info.value)


def test_template_that_only_warns_with_real_table_names_is_a_config_error(tmp_path):
    # an empty created name makes `[x|@TABLES@|]` read `[x||]`: a FutureWarning ("possible set union"), an error here
    toml = "[sql]\ncreate = ['DEFINE (\\w*);']\nuse = ['([x|@TABLES@|])']\n"
    cfg = make_config(tmp_path, toml)
    mods = scan({"a.py": b"X = 'DEFINE ;'\n"}, cfg)
    with pytest.raises(ConfigError) as info:
        derive_facts(mods, cfg)
    assert "[sql] use" in str(info.value)


def test_template_capture_that_is_not_a_created_table_is_ignored(tmp_path):
    # config only checks that a template has one capture group; the group may capture more than the table name
    toml = "[sql]\nuse = ['\\bFROM\\s+(@TABLES@\\w*)']\n"
    files = {
        "a.py": 'X = "CREATE TABLE orders (id INT)"\n',
        "b.py": 'Y = "SELECT * FROM orders_old"\nZ = "SELECT * FROM orders"\n',
    }
    assert facts_of(tmp_path, files, toml).tables == {"orders": {"b"}}
