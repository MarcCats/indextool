<!-- indextool:begin (managed: change indextool.toml, not this block) -->
- `docs/architecture.md` - generated map of layout, dependency layers, import cycles, routes, tables and what writes them, and the most-used modules. Read it whole for whole-repo questions. Regenerated from code, never edited by hand.
- `docs/architecture.index.txt` - generated one-line-per-module index (title, library or standalone, io, tables, routes). Search it with grep for where something lives or which modules read or write a table. It is large: do not read it whole.
- Regenerate with `indextool generate`. CI runs `indextool verify` and fails when either file is stale.
<!-- indextool:end -->
