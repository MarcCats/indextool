import warnings

import pytest

from indextool.errors import ConfigError
from indextool.scan import SENTINEL, module_key, resolve_edges, scan
from tests.helpers import make_config


def run_scan(directory, files, toml=""):
    cfg = make_config(directory, toml)
    data = {path: (c.encode("utf-8") if isinstance(c, str) else c) for path, c in files.items()}
    mods = scan(data, cfg)
    resolve_edges(mods)
    return mods


def test_module_keys():
    assert module_key("pkg/mod.py") == ("pkg.mod", False)
    assert module_key("pkg/__init__.py") == ("pkg", True)
    assert module_key("top.py") == ("top", False)
    assert module_key("__init__.py") == ("", True)


def test_roots_relativize_keys_and_files_outside_are_ignored(tmp_path):
    mods = run_scan(
        tmp_path,
        {"src/shop/orders.py": "", "src/shop/__init__.py": "", "tools/x.py": "", "__init__.py": ""},
        'roots = ["src"]\n',
    )
    assert list(mods) == ["shop", "shop.orders"]
    assert mods["shop"].is_package and not mods["shop.orders"].is_package


def test_two_files_with_the_same_key_are_an_error(tmp_path):
    with pytest.raises(ConfigError, match="both map to the key 'util'"):
        run_scan(tmp_path, {"src/util.py": "", "lib/util.py": ""}, 'roots = ["src", "lib"]\n')


def test_test_modules_follow_the_tests_patterns(tmp_path):
    mods = run_scan(
        tmp_path,
        {"shop/orders.py": "", "shop/test_orders.py": "", "tests/conftest.py": "", "shop/orders_test.py": ""},
    )
    assert {k for k, m in mods.items() if m.is_test} == {"shop.test_orders", "tests.conftest", "shop.orders_test"}


def test_first_docstring_line_and_main_guard(tmp_path):
    mods = run_scan(
        tmp_path,
        {
            "a.py": '"""\n\n  Order ledger.\n\nMore text.\n"""\nif __name__ == "__main__":\n    pass\n',
            "b.py": "x = 1\n",
        },
    )
    assert mods["a"].doc == "Order ledger." and mods["a"].has_main is True
    assert mods["b"].doc == "" and mods["b"].has_main is False


def test_a_docstring_with_a_form_feed_and_u2028_stays_one_line(tmp_path):
    mods = run_scan(tmp_path, {"a.py": '"""Alpha\\x0cbeta\\u2028gamma"""\n'})
    assert mods["a"].doc == "Alpha\x0cbeta gamma"


def test_public_classes_and_upper_case_constant_tables(tmp_path):
    src = "class Money: pass\nclass _Hidden: pass\nRATES = {'a': 1}\nNAMES = ['x']\nLIMIT = 5\n_PRIVATE = (1,)\n"
    mod = run_scan(tmp_path, {"a.py": src})["a"]
    assert mod.classes == ("Money",) and mod.constants == ("RATES", "NAMES")


def test_edges_absolute_relative_and_submodule_imports(tmp_path):
    files = {
        "shop/__init__.py": "",
        "shop/orders.py": "from . import ledger\nfrom .ledger import Money\nimport shop.web\nimport os.path\n",
        "shop/ledger.py": "class Money: pass\n",
        "shop/web.py": "from shop import orders as o\nfrom shop.missing import x\nfrom .. import nothing\n",
        "shop/sub/__init__.py": "from ..ledger import Money\n",
    }
    mods = run_scan(tmp_path, files)
    assert mods["shop.orders"].edges == {"shop", "shop.ledger", "shop.web"}
    assert mods["shop.web"].edges == {"shop", "shop.orders"}
    assert mods["shop.sub"].edges == {"shop.ledger"}


def test_function_level_and_conditional_imports_are_edges(tmp_path):
    src = "import a\n\ndef f():\n    import b\n\ntry:\n    import c\nexcept ImportError:\n    pass\n"
    mods = run_scan(tmp_path, {"m.py": src, "a.py": "", "b.py": "", "c.py": ""})
    assert mods["m"].edges == {"a", "b", "c"}


def test_routes_require_a_listed_decorator_and_a_literal_path_starting_with_a_slash(tmp_path):
    src = (
        "@app.route('/orders')\ndef a(): pass\n"
        "@bp.get('/orders/<int:id>')\nasync def b(): pass\n"
        "@cache.delete('user')\ndef c(): pass\n"
        "@app.route(path)\ndef d(): pass\n"
        "@retry.get\ndef e(): pass\n"
        "@app.custom('/x')\ndef f(): pass\n"
    )
    assert run_scan(tmp_path, {"web.py": src})["web"].routes == ("/orders", "/orders/<int:id>")


def test_literals_skip_docstrings_and_mark_fstring_values(tmp_path):
    src = '"""Docs mention INSERT INTO ghost."""\nq = "SELECT 1"\nr = f"INSERT INTO t VALUES ({1})"\n'
    literals = run_scan(tmp_path, {"m.py": src})["m"].literals
    assert "SELECT 1" in literals
    assert f"INSERT INTO t VALUES ({SENTINEL})" in literals
    assert not any("ghost" in s for s in literals)


def test_to_sql_calls_are_noticed(tmp_path):
    mods = run_scan(tmp_path, {"a.py": "df.to_sql('t', con)\n", "b.py": "x = 1\n"})
    assert mods["a"].calls_to_sql is True and mods["b"].calls_to_sql is False


@pytest.mark.parametrize(
    "data",
    [
        b"def broken(:\n",
        ("x = " + "(" * 300 + "1" + ")" * 300 + "\n").encode(),
        b"# coding: nosuchcodec\nx = 1\n",
        b"\xef\xbb\xbf# coding: latin-1\nx = 1\n",
    ],
)
def test_unparsable_files_are_counted_modules_with_only_their_raw_text(tmp_path, data):
    mod = run_scan(tmp_path, {"bad.py": data})["bad"]
    assert mod.parse_error is True
    assert mod.imports == () and mod.edges == frozenset() and mod.doc == "" and mod.routes == ()
    assert len(mod.literals) == 1


def test_a_condition_too_deep_to_unparse_does_not_crash_or_hide_the_rest_of_the_file(tmp_path):
    # ast.parse copes with a long chain, but ast.unparse (used for the main-guard check) recurses per level
    deep = "if " + " + ".join(["1"] * 500) + " == 3:\n    pass\n"
    mod = run_scan(tmp_path, {"m.py": "import os\n" + deep + "if __name__ == '__main__':\n    pass\n"})["m"]
    assert mod.parse_error is False and mod.has_main is True and len(mod.imports) == 1


def test_source_nested_beyond_the_parser_stack_is_an_unparsable_module(tmp_path):
    mod = run_scan(tmp_path, {"deep.py": "x = " + "lambda: " * 5000 + "1\n"})["deep"]
    assert mod.parse_error is True and mod.imports == () and len(mod.literals) == 1


def test_a_parser_warning_does_not_make_a_valid_file_unparsable(tmp_path):
    cfg = make_config(tmp_path)
    source = "import os\n" + r'pattern = "\d+"' + "\n"  # an invalid escape: the parser warns about it
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # what -W error does
        mod = scan({"rx.py": source.encode("utf-8")}, cfg)["rx"]
    assert mod.parse_error is False and mod.literals == (r"\d+",)


def test_non_ascii_paths_and_docstrings(tmp_path):
    mods = run_scan(tmp_path, {"café/naïve.py": '"""Crème brûlée."""\n'})
    assert list(mods) == ["café.naïve"]
    assert mods["café.naïve"].doc == "Crème brûlée."


def test_scan_is_independent_of_input_order(tmp_path):
    files = {"a.py": "import b\n", "b.py": "", "c.py": "import a\n"}
    first = run_scan(tmp_path, files)
    second = run_scan(tmp_path, dict(reversed(list(files.items()))))
    assert list(first) == list(second) == ["a", "b", "c"]
    assert first == second
