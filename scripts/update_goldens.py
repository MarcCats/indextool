"""Regenerate tests/golden/* from the portable fixture. Usage: python scripts/update_goldens.py"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.fixture_repos import PORTABLE  # noqa: E402
from tests.helpers import make_repo, run_cli  # noqa: E402

GOLDEN = ROOT / "tests" / "golden"


def main() -> int:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:  # git object files are read-only on Windows
        repo = make_repo(Path(tmp), PORTABLE, name="portable")
        result = run_cli(repo, "generate")
        if result.code != 0:
            print(result.err, file=sys.stderr)
            return 1
        GOLDEN.mkdir(parents=True, exist_ok=True)
        (GOLDEN / "portable.architecture.md").write_bytes((repo / "docs" / "architecture.md").read_bytes())
        (GOLDEN / "portable.index.txt").write_bytes((repo / "docs" / "architecture.index.txt").read_bytes())
    print(f"updated {GOLDEN}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
