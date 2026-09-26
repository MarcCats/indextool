"""Parse each discovered file once and keep what the map needs."""
from __future__ import annotations

import ast
import warnings
from dataclasses import dataclass

from .config import Config
from .decode import decode_source
from .errors import ConfigError

SENTINEL = ""  # stands where an f-string holds a value


@dataclass(frozen=True)
class ImportSpec:
    level: int
    module: str
    names: tuple[str, ...]


@dataclass
class Module:
    key: str
    path: str
    is_package: bool
    is_test: bool
    parse_error: bool = False
    doc: str = ""
    has_main: bool = False
    imports: tuple[ImportSpec, ...] = ()
    classes: tuple[str, ...] = ()
    constants: tuple[str, ...] = ()
    literals: tuple[str, ...] = ()
    routes: tuple[str, ...] = ()
    calls_to_sql: bool = False
    edges: frozenset[str] = frozenset()


def module_key(inner: str) -> tuple[str, bool]:
    parts = inner[:-3].split("/")
    is_package = parts[-1] == "__init__"
    if is_package:
        parts.pop()
    return ".".join(parts), is_package


def _within_root(path: str, roots: tuple[str, ...]) -> str | None:
    for root in roots:
        if root == ".":
            return path
        if path.startswith(root + "/"):
            return path[len(root) + 1 :]
    return None


def _first_doc_line(tree: ast.Module) -> str:
    doc = ast.get_docstring(tree) or ""
    for line in doc.split("\n"):
        if line.strip():
            return line.strip()
    return ""


def _has_main_guard(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.If):
            try:
                text = ast.unparse(node.test)
            except RecursionError:  # a test nested deeper than unparse can walk is not `__name__ == "__main__"`
                continue
            if "__name__" in text and "__main__" in text:
                return True
    return False


def _top_level_names(tree: ast.Module) -> tuple[tuple[str, ...], tuple[str, ...]]:
    classes: list[str] = []
    constants: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            classes.append(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(
            node.value, (ast.Dict, ast.List, ast.Tuple, ast.Set)
        ):
            for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                if isinstance(target, ast.Name) and target.id.isupper() and not target.id.startswith("_"):
                    constants.append(target.id)
    return tuple(classes), tuple(constants)


def _collect_imports(tree: ast.Module) -> tuple[ImportSpec, ...]:
    specs: list[ImportSpec] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            specs.extend(ImportSpec(0, alias.name, ()) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            specs.append(ImportSpec(node.level, node.module or "", tuple(a.name for a in node.names)))
    return tuple(specs)


def _string_literals(tree: ast.Module) -> tuple[str, ...]:
    """Every string literal except docstrings; an f-string is one string with SENTINEL where a value goes."""
    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                skip.add(id(first.value))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            skip.update(id(v) for v in node.values)
            out.append(
                "".join(
                    v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else SENTINEL
                    for v in node.values
                )
            )
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            out.append(node.value)
    return tuple(out)


def _routes_in(tree: ast.Module, decorators: frozenset[str]) -> tuple[str, ...]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for deco in node.decorator_list:
                if (
                    isinstance(deco, ast.Call)
                    and isinstance(deco.func, ast.Attribute)
                    and deco.func.attr in decorators
                    and deco.args
                    and isinstance(deco.args[0], ast.Constant)
                    and isinstance(deco.args[0].value, str)
                    and deco.args[0].value.startswith("/")
                ):
                    found.append((deco.lineno, deco.args[0].value))
    return tuple(path for _line, path in sorted(found))


def _parse(key: str, path: str, is_package: bool, data: bytes, is_test: bool, decorators: frozenset[str]) -> Module:
    text, encoding_ok = decode_source(data)
    mod = Module(key=key, path=path, is_package=is_package, is_test=is_test)
    tree = None
    if encoding_ok:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # invalid escapes and the like: neither noise nor a reason to give up
                tree = ast.parse(text)
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            tree = None
    if tree is None:
        mod.parse_error = True
        mod.literals = (text,)
        return mod
    mod.doc = _first_doc_line(tree)
    mod.has_main = _has_main_guard(tree)
    mod.imports = _collect_imports(tree)
    mod.classes, mod.constants = _top_level_names(tree)
    mod.literals = _string_literals(tree)
    mod.routes = _routes_in(tree, decorators)
    mod.calls_to_sql = any(isinstance(n, ast.Attribute) and n.attr == "to_sql" for n in ast.walk(tree))
    return mod


def scan(files: dict[str, bytes], cfg: Config) -> dict[str, Module]:
    mods: dict[str, Module] = {}
    decorators = frozenset(cfg.route_decorators)
    for path in sorted(files):
        inner = _within_root(path, cfg.roots)
        if inner is None:
            continue
        key, is_package = module_key(inner)
        if not key:
            continue
        if key in mods:
            raise ConfigError(f"modules {mods[key].path} and {path} both map to the key {key!r}")
        mods[key] = _parse(key, path, is_package, files[path], cfg.tests.matches(path), decorators)
    return mods


def _longest_known(dotted: str, known: set[str]) -> str | None:
    parts = dotted.split(".") if dotted else []
    while parts:
        candidate = ".".join(parts)
        if candidate in known:
            return candidate
        parts.pop()
    return None


def _resolve(spec: ImportSpec, importer: Module, known: set[str]) -> set[str]:
    if spec.level == 0 and not spec.names:  # `import a.b`
        hit = _longest_known(spec.module, known)
        return {hit} if hit else set()
    out: set[str] = set()
    if spec.level == 0:
        base = spec.module
    else:
        pkg = importer.key.split(".") if importer.key else []
        if not importer.is_package:
            pkg = pkg[:-1]
        up = spec.level - 1
        if up > len(pkg):
            return out
        pkg = pkg[: len(pkg) - up]
        base = ".".join(pkg + ([spec.module] if spec.module else []))
    hit = _longest_known(base, known)
    if hit:
        out.add(hit)
    for name in spec.names:
        sub = f"{base}.{name}" if base else name
        if sub in known:
            out.add(sub)
    return out


def resolve_edges(mods: dict[str, Module]) -> None:
    known = set(mods)
    for mod in mods.values():
        edges: set[str] = set()
        for spec in mod.imports:
            edges |= _resolve(spec, mod, known)
        edges.discard(mod.key)
        mod.edges = frozenset(edges)
