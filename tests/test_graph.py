from indextool.graph import (
    compute_depths,
    dependents,
    find_cycles,
    find_duplicate_names,
    importers,
    library_modules,
)
from indextool.scan import Module


def mk(key, edges=(), is_test=False, classes=(), constants=()):
    return Module(
        key=key,
        path=key.replace(".", "/") + ".py",
        is_package=False,
        is_test=is_test,
        edges=frozenset(edges),
        classes=tuple(classes),
        constants=tuple(constants),
    )


def graph_of(*modules):
    return {m.key: m for m in modules}


def test_dependents_and_importers_ignore_test_importers_only_in_importers():
    mods = graph_of(mk("a", ["b"]), mk("b"), mk("test_b", ["b"], is_test=True))
    assert dependents(mods)["b"] == {"a", "test_b"}
    assert importers(mods)["b"] == ["a"]


def test_library_and_standalone_ignore_test_importers():
    mods = graph_of(mk("a", ["b"]), mk("b"), mk("test_c", ["c"], is_test=True), mk("c"))
    assert library_modules(mods) == {"b"}  # c is imported only by a test module


def test_depth_is_one_more_than_the_deepest_import():
    mods = graph_of(mk("top", ["mid", "leaf"]), mk("mid", ["leaf"]), mk("leaf"), mk("alone"))
    assert compute_depths(mods) == {"top": 2, "mid": 1, "leaf": 0, "alone": 0}


def test_depth_ignores_test_modules():
    mods = graph_of(mk("a"), mk("test_a", ["a"], is_test=True))
    assert compute_depths(mods) == {"a": 0}


def test_cycle_members_share_a_depth_and_are_reported():
    mods = graph_of(mk("x", ["y"]), mk("y", ["z"]), mk("z", ["x", "base"]), mk("base"), mk("app", ["x"]))
    assert find_cycles(mods) == [["x", "y", "z"]]
    depths = compute_depths(mods)
    assert depths["x"] == depths["y"] == depths["z"] == 1
    assert depths["app"] == 2 and depths["base"] == 0


def test_cycles_are_ordered_largest_first_then_by_name():
    mods = graph_of(mk("a", ["b"]), mk("b", ["a"]), mk("c", ["d"]), mk("d", ["e"]), mk("e", ["c"]))
    assert find_cycles(mods) == [["c", "d", "e"], ["a", "b"]]


def test_no_cycles_in_a_dag():
    assert find_cycles(graph_of(mk("a", ["b"]), mk("b"))) == []


def test_duplicate_names_need_two_library_definitions():
    mods = graph_of(
        mk("app", ["one", "two"]),
        mk("one", classes=["Money"], constants=["RATES"]),
        mk("two", classes=["Money"]),
        mk("script", classes=["Money", "Solo"]),
        mk("test_x", classes=["Money"], is_test=True),
    )
    assert find_duplicate_names(mods) == [("class", "Money", ["one", "script", "two"])]


# --- scale, determinism and edge cases (binding rules for this task) ---

CHAIN = 5000


def test_long_import_chain_does_not_recurse():
    # m0 imports m1 imports ... imports m4999; well beyond the default recursion limit
    mods = graph_of(*(mk(f"m{i:05d}", [f"m{i + 1:05d}"] if i + 1 < CHAIN else []) for i in range(CHAIN)))
    assert find_cycles(mods) == []
    depths = compute_depths(mods)
    assert depths["m00000"] == CHAIN - 1
    assert depths[f"m{CHAIN - 1:05d}"] == 0
    assert len(depths) == CHAIN


def test_large_cycle_is_one_component_and_shares_a_depth():
    names = [f"c{i:05d}" for i in range(CHAIN)]
    members = [mk(n, [names[(i + 1) % CHAIN]]) for i, n in enumerate(names)]
    mods = graph_of(*members, mk("base"), mk("app", [names[0]]))
    mods["c00007"] = mk("c00007", [names[8], "base"])
    assert find_cycles(mods) == [sorted(names)]
    depths = compute_depths(mods)
    assert {depths[n] for n in names} == {1}
    assert depths["app"] == 2 and depths["base"] == 0


def test_cycle_containing_a_test_module_is_not_a_cycle_and_does_not_change_library_depths():
    # a <-> t where t is a test: cycles are over non-test modules only, so there is none
    mods = graph_of(mk("a", ["t"]), mk("t", ["a"], is_test=True), mk("b", ["a"]))
    assert find_cycles(mods) == []
    assert compute_depths(mods) == {"a": 0, "b": 1}


def test_two_test_modules_importing_each_other_are_not_a_cycle():
    mods = graph_of(mk("test_a", ["test_b"], is_test=True), mk("test_b", ["test_a"], is_test=True), mk("lib"))
    assert find_cycles(mods) == []


def test_self_import_is_not_a_cycle_and_does_not_add_depth():
    mods = graph_of(mk("a", ["a", "b"]), mk("b"))
    assert find_cycles(mods) == []
    assert compute_depths(mods) == {"a": 1, "b": 0}


def test_edges_to_unknown_modules_are_ignored():
    mods = graph_of(mk("a", ["ghost", "b"]), mk("b", ["ghost"]))
    assert dependents(mods) == {"a": set(), "b": {"a"}}
    assert find_cycles(mods) == []
    assert compute_depths(mods) == {"a": 1, "b": 0}


def test_results_do_not_depend_on_insertion_order():
    modules = [
        mk("app", ["one", "two", "x"]),
        mk("one", ["base"], classes=["Money"], constants=["RATES"]),
        mk("two", ["base"], classes=["Money"], constants=["RATES"]),
        mk("x", ["y"]),
        mk("y", ["x"]),
        mk("base"),
        mk("test_one", ["one"], is_test=True),
    ]
    forward = graph_of(*modules)
    backward = graph_of(*reversed(modules))
    assert find_cycles(forward) == find_cycles(backward) == [["x", "y"]]
    assert compute_depths(forward) == compute_depths(backward)
    assert importers(forward) == importers(backward)
    assert find_duplicate_names(forward) == find_duplicate_names(backward)
    assert library_modules(forward) == library_modules(backward)


def test_duplicate_names_are_ordered_by_count_then_name_then_kind():
    mods = graph_of(
        mk("app", ["a", "b", "c"]),
        mk("a", classes=["Zed", "Money"], constants=["Money", "LIMIT"]),
        mk("b", classes=["Zed", "Money"], constants=["Money", "LIMIT"]),
        mk("c", classes=["Zed"]),
    )
    assert find_duplicate_names(mods) == [
        ("class", "Zed", ["a", "b", "c"]),
        ("constant", "LIMIT", ["a", "b"]),
        ("class", "Money", ["a", "b"]),
        ("constant", "Money", ["a", "b"]),
    ]


def test_a_name_listed_twice_in_one_module_counts_once():
    mods = graph_of(mk("app", ["a"]), mk("a", classes=["Money", "Money"]))
    assert find_duplicate_names(mods) == []


def test_a_repeated_name_lists_its_module_once():
    mods = graph_of(
        mk("app", ["a", "b"]),
        mk("a", classes=["Money", "Money"], constants=["RATES", "RATES"]),
        mk("b", classes=["Money"], constants=["RATES"]),
    )
    assert find_duplicate_names(mods) == [("class", "Money", ["a", "b"]), ("constant", "RATES", ["a", "b"])]


def test_test_modules_are_not_part_of_the_depth_graph_even_inside_a_cycle():
    # a -> t -> b -> a runs through a test module; without t there is only b -> a, so no cycle among non-tests
    mods = graph_of(mk("a", ["t"]), mk("t", ["b"], is_test=True), mk("b", ["a"]))
    assert compute_depths(mods) == {"a": 0, "b": 1}


def test_empty_graph():
    assert dependents({}) == {}
    assert importers({}) == {}
    assert library_modules({}) == set()
    assert find_cycles({}) == []
    assert compute_depths({}) == {}
    assert find_duplicate_names({}) == []
