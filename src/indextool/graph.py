"""Graph rules over module records: who imports whom, depth, cycles, look-alike names."""
from __future__ import annotations

from .scan import Module


def dependents(mods: dict[str, Module]) -> dict[str, set[str]]:
    rev: dict[str, set[str]] = {key: set() for key in mods}
    for mod in mods.values():
        for dep in mod.edges:
            if dep in rev:
                rev[dep].add(mod.key)
    return rev


def importers(mods: dict[str, Module]) -> dict[str, list[str]]:
    rev = dependents(mods)
    return {key: sorted(i for i in rev[key] if not mods[i].is_test) for key in mods}


def library_modules(mods: dict[str, Module]) -> set[str]:
    imp = importers(mods)
    return {key for key, mod in mods.items() if not mod.is_test and imp[key]}


def find_cycles(mods: dict[str, Module]) -> list[list[str]]:
    """Import cycles: strongly connected components of two or more non-test modules (iterative Tarjan). Test modules
    are not part of the graph, so a cycle that only closes through a test module is not reported."""
    mods = {key: mod for key, mod in mods.items() if not mod.is_test}
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    sccs: list[list[str]] = []
    counter = 0
    for start in sorted(mods):
        if start in index:
            continue
        index[start] = low[start] = counter
        counter += 1
        stack.append(start)
        on_stack.add(start)
        work = [(start, iter(sorted(mods[start].edges)))]
        while work:
            node, it = work[-1]
            descended = False
            for nxt in it:
                if nxt not in mods:
                    continue
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(sorted(mods[nxt].edges))))
                    descended = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if descended:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                comp: list[str] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    comp.append(member)
                    if member == node:
                        break
                if len(comp) > 1:
                    sccs.append(sorted(comp))
    return sorted(sccs, key=lambda c: (-len(c), c))


def compute_depths(mods: dict[str, Module]) -> dict[str, int]:
    """Depth of every non-test module: 0 when it imports no other module here, otherwise one more than the deepest
    module it imports. Modules in an import cycle share one depth. Tests are not part of the graph."""
    keys = {k for k, m in mods.items() if not m.is_test}
    node_of = {k: ("cycle", i) for i, comp in enumerate(find_cycles(mods)) for k in comp}
    deps: dict = {}
    for k in sorted(keys):
        node = node_of.get(k, k)
        deps.setdefault(node, set()).update(node_of.get(d, d) for d in mods[k].edges if d in keys)
        deps[node].discard(node)
    depth: dict = {}
    for start in sorted(deps, key=repr):
        if start in depth:
            continue
        active = {start}
        stack = [(start, iter(sorted(deps[start], key=repr)))]
        while stack:
            node, pending = stack[-1]
            for nxt in pending:
                if nxt not in depth and nxt not in active:
                    active.add(nxt)
                    stack.append((nxt, iter(sorted(deps[nxt], key=repr))))
                    break
            else:
                depth[node] = 1 + max((depth[d] for d in deps[node] if d in depth), default=-1)
                active.discard(node)
                stack.pop()
    return {k: depth[node_of.get(k, k)] for k in sorted(keys)}


def find_duplicate_names(mods: dict[str, Module]) -> list[tuple[str, str, list[str]]]:
    """A class or constant table that two or more library modules define, most definitions first. Copies in standalone
    scripts are listed with the others but do not make a name a duplicate."""
    library = library_modules(mods)
    where: dict[tuple[str, str], list[str]] = {}
    for mod in mods.values():
        if mod.is_test:
            continue
        for name in set(mod.classes):  # a name redefined inside one module is still one definition
            where.setdefault(("class", name), []).append(mod.key)
        for name in set(mod.constants):
            where.setdefault(("constant", name), []).append(mod.key)
    rows = [
        (kind, name, sorted(keys))
        for (kind, name), keys in where.items()
        if sum(1 for k in keys if k in library) >= 2
    ]
    return sorted(rows, key=lambda r: (-len(r[2]), r[1], r[0]))
