# What indextool computes

Every rule below is pinned by a test, named in the right-hand column. `scripts/check_doc_tests.py` fails CI when a
cited test does not exist, so this page cannot silently drift from the code.

## Which files are read

| Rule | Pinned by |
|---|---|
| In a git work tree only tracked regular `.py` files count, sorted by path; untracked files never do. | `tests/test_sources.py::test_git_mode_lists_tracked_python_files_only_and_sorted` |
| Symlinks and gitlinks are skipped by their index mode, identically on every OS. | `tests/test_sources.py::test_symlink_and_gitlink_entries_are_skipped_by_mode` |
| A tracked file deleted from the working tree is skipped in worktree mode. | `tests/test_sources.py::test_tracked_but_deleted_files_are_skipped_in_worktree_mode` |
| `--source index` reads the staged content, not the working tree. | `tests/test_sources.py::test_index_source_reads_staged_content_not_the_working_tree` |
| `exclude` patterns remove files and the count is reported. | `tests/test_sources.py::test_exclude_patterns_drop_files_and_are_counted` |
| Two paths that differ only by case are an error. | `tests/test_sources.py::test_paths_that_differ_only_by_case_are_an_error` |
| Unmerged index entries are an error. | `tests/test_sources.py::test_unmerged_paths_are_an_error` |
| Outside git a sorted walk skips `venv`, `node_modules`, `__pycache__` and similar directories. | `tests/test_sources.py::test_walk_mode_skips_default_excludes_and_symlinks_and_is_sorted` |
| Sources are decoded by their PEP 263 cookie or BOM, never the locale; newlines become LF. | `tests/test_decode.py::test_bom_is_stripped_and_newlines_are_normalized` and `tests/test_decode.py::test_latin1_cookie_is_honoured` |
| A bad cookie or a BOM/cookie mismatch makes the file an unparsable module, never a crash. | `tests/test_decode.py::test_unknown_cookie_and_bom_mismatch_are_not_ok_and_never_raise` |
| Globs follow gitignore rules without negation. | `tests/test_globs.py::test_glob_matching` |

## Configuration

| Rule | Pinned by |
|---|---|
| The config is found by searching upward from the working directory, and its directory is the base directory. | `tests/test_config.py::test_config_is_found_by_searching_upward_and_base_is_its_directory` |
| The search stops at the git top level; with no config the base is the git top level. | `tests/test_config.py::test_search_stops_at_the_git_top_level` and `tests/test_config.py::test_without_a_config_the_base_is_the_git_top_level` |
| `indextool.toml` wins over the `[tool.indextool]` table of `pyproject.toml`. | `tests/test_config.py::test_indextool_toml_wins_over_pyproject` |
| A config file that git does not track is flagged, and `verify` exits 2 naming it. | `tests/test_config.py::test_untracked_config_is_flagged` and `tests/test_cli_verify_refresh.py::test_verify_names_an_untracked_config_and_exits_2` |
| Under `--source index` the config is read from the index too: a config that was never staged is simply not found, so the defaults apply, with no error. | `tests/test_config.py::test_source_index_locates_indextool_toml_from_the_index_too` |
| A `--config` path outside the repository is an error. | `tests/test_config.py::test_explicit_config_outside_the_repository_is_an_error` |

## Modules and import edges

| Rule | Pinned by |
|---|---|
| A module key is its path under a root, dotted; `pkg/__init__.py` is `pkg`. | `tests/test_scan.py::test_module_keys` |
| Roots relativize keys; files outside every root are ignored. | `tests/test_scan.py::test_roots_relativize_keys_and_files_outside_are_ignored` |
| Two files with the same key are an error. | `tests/test_scan.py::test_two_files_with_the_same_key_are_an_error` |
| A test module matches a `tests` pattern and appears only in the module count. | `tests/test_scan.py::test_test_modules_follow_the_tests_patterns` |
| Absolute, relative and submodule imports resolve to the longest known repository module; the rest are dropped. | `tests/test_scan.py::test_edges_absolute_relative_and_submodule_imports` |
| Function-level and conditional imports are edges. | `tests/test_scan.py::test_function_level_and_conditional_imports_are_edges` |
| A file that cannot be parsed is a module with no imports, and is counted. | `tests/test_scan.py::test_unparsable_files_are_counted_modules_with_only_their_raw_text` |
| The title is the first non-empty docstring line; lines are split on `\n` only. | `tests/test_scan.py::test_a_docstring_with_a_form_feed_and_u2028_stays_one_line` |

## Graph

| Rule | Pinned by |
|---|---|
| A library module has at least one non-test importer; the rest are standalone. | `tests/test_graph.py::test_library_and_standalone_ignore_test_importers` |
| Depth is one more than the deepest import; tests are ignored. | `tests/test_graph.py::test_depth_is_one_more_than_the_deepest_import` |
| Modules in a cycle share a depth. | `tests/test_graph.py::test_cycle_members_share_a_depth_and_are_reported` |
| Cycles are found among non-test modules only: a loop that closes only through a test module is not a cycle. | `tests/test_graph.py::test_cycle_containing_a_test_module_is_not_a_cycle_and_does_not_change_library_depths` and `tests/test_graph.py::test_two_test_modules_importing_each_other_are_not_a_cycle` |
| Cycles are ordered largest first, then by name. | `tests/test_graph.py::test_cycles_are_ordered_largest_first_then_by_name` |
| A name is a look-alike when two or more library modules define it. | `tests/test_graph.py::test_duplicate_names_need_two_library_definitions` |

## Tables, routes and IO

| Rule | Pinned by |
|---|---|
| Tables, users and writers come from `CREATE TABLE` in string literals. | `tests/test_facts.py::test_created_tables_users_and_writers` |
| Docstrings and comments are not evidence; f-string values stand in as `?`. | `tests/test_facts.py::test_docstrings_and_comments_are_not_evidence_and_fstrings_count` |
| Table names are escaped and matched longest first. | `tests/test_facts.py::test_custom_create_pattern_and_table_names_are_escaped` |
| Test modules contribute no facts. | `tests/test_facts.py::test_test_modules_contribute_nothing` |
| A route is a listed decorator call with a literal first argument starting with `/`. | `tests/test_scan.py::test_routes_require_a_listed_decorator_and_a_literal_path_starting_with_a_slash` |
| The IO rating comes from imports matched by dotted prefix; SQL text alone is not evidence. | `tests/test_facts.py::test_io_rating` |

## Output

| Rule | Pinned by |
|---|---|
| The header carries the title and `indextool <major.minor>`; the numbers section counts what it says. | `tests/test_render.py::test_header_and_numbers` |
| Every capped list of lines ends with a `(+N more)` line (`(+N more tables)`, `(+N more cycles)` and so on). | `tests/test_render.py::test_lists_are_capped_with_a_more_line` |
| Detector lines and the "cannot say" list come from the active config. | `tests/test_render.py::test_detector_lines_and_cannot_say_reflect_the_config` |
| The index has one line per non-test module. | `tests/test_render.py::test_index_lines` |
| The output does not depend on input order. | `tests/test_render.py::test_output_does_not_depend_on_input_order` |

## Determinism and verification

| Rule | Pinned by |
|---|---|
| Hash seed, working directory, CRLF and locale do not change a byte. | `tests/test_determinism.py::test_hash_seed_does_not_matter`, `tests/test_determinism.py::test_working_directory_does_not_matter`, `tests/test_determinism.py::test_crlf_sources_produce_identical_output` and `tests/test_determinism.py::test_locale_and_utf8_mode_do_not_matter_and_the_latin1_cookie_is_honoured` |
| A renamed copy (a different folder name) produces identical output. | `tests/test_determinism.py::test_renamed_copies_produce_identical_output` |
| Untracked files and default-excluded directories change nothing. | `tests/test_determinism.py::test_untracked_files_and_default_excluded_directories_change_nothing` |
| Worktree and index outputs match on a clean tree and differ on a dirty one. | `tests/test_determinism.py::test_worktree_and_index_outputs_match_on_a_clean_tree_and_differ_on_a_dirty_one` |
| The portable fixture matches its golden output on every OS and Python. | `tests/test_golden.py::test_portable_fixture_matches_the_golden_output` |
| `verify` fails on drift and says how to fix it. | `tests/test_cli_verify_refresh.py::test_verify_fails_when_an_import_changes_and_says_how_to_fix_it` |
| `verify` accepts CRLF in the committed map. | `tests/test_cli_verify_refresh.py::test_verify_accepts_crlf_line_endings_in_the_committed_map` |
| `verify --source index` checks what would be committed. | `tests/test_cli_verify_refresh.py::test_index_source_checks_what_would_be_committed` |
| In worktree mode `verify` warns on stderr, without changing its exit code, when files it reads have unstaged changes: CI would see the committed version. The warning watches the tracked Python files, the config and the pointer files. | `tests/test_cli_verify_refresh.py::test_an_unstaged_edit_warns_in_worktree_mode` |
| An untracked config makes `verify` exit 2, naming it. | `tests/test_cli_verify_refresh.py::test_verify_names_an_untracked_config_and_exits_2` |
| `refresh` is silent, fails open and never replaces a good map with an empty one. | `tests/test_cli_verify_refresh.py::test_refresh_never_replaces_a_good_map_with_an_empty_one` |
| A hand-edited pointer block makes `verify` exit 2. | `tests/test_pointer.py::test_verify_exits_2_when_a_block_was_edited_by_hand` |

## The pointer block and `init`

| Rule | Pinned by |
|---|---|
| The pointer goes into `AGENTS.md` when no instruction file exists or `CLAUDE.md` imports `@AGENTS.md`; otherwise into every existing one of `CLAUDE.md`, `.claude/CLAUDE.md` and `AGENTS.md`. | `tests/test_pointer.py::test_placement` |
| A marker counts only as a whole line outside fenced code: a prose mention or a quoted example is not a block. | `tests/test_pointer.py::test_a_prose_mention_of_the_markers_is_not_a_block` and `tests/test_pointer.py::test_a_fenced_example_is_skipped_in_favour_of_the_real_block` |
| Unpaired or duplicate markers are refused, never guessed at: `init` writes nothing and `verify` exits 2 without touching the file. | `tests/test_pointer.py::test_upsert_refuses_an_unpaired_marker_and_returns_nothing_to_write`, `tests/test_pointer.py::test_upsert_refuses_a_second_block` and `tests/test_pointer.py::test_verify_exits_2_on_an_unpaired_marker_and_leaves_the_file_alone` |
| `init` never overwrites an existing config or workflow. | `tests/test_init.py::test_existing_config_is_never_overwritten` and `tests/test_init.py::test_the_workflow_is_not_overwritten` |
| `init` is idempotent, and `--dry-run` writes nothing. | `tests/test_init.py::test_init_is_idempotent` and `tests/test_init.py::test_dry_run_writes_nothing` |
| `init` refreshes a stale managed block in every candidate file that already holds one, and adds a block to no other file. | `tests/test_init.py::test_a_stale_block_in_a_file_that_is_not_a_target_is_refreshed_but_no_block_is_added_elsewhere` |
| `init` keeps a CRLF file CRLF and does not rewrite a file that is already up to date. | `tests/test_init.py::test_files_that_use_crlf_keep_it_and_an_up_to_date_file_is_not_rewritten` |
| `init` writes through a symlink, so the link stays a link. | `tests/test_init.py::test_a_symlinked_pointer_file_stays_a_link_and_both_names_show_one_block` |
| Every path `init` prints is relative to the shell directory. | `tests/test_init.py::test_every_printed_path_is_relative_to_the_shell_directory` |

## What the map cannot see

Why a module exists, how modules cooperate beyond importing each other, formulas and thresholds, imports made through
`importlib`, `exec` or `sys.path` changes, tables not created by a matching `CREATE TABLE` in a string literal, routes
not registered by a listed decorator with a literal `/` path, and anything that is not Python source. Every generated
map states this in its closing section, built from the active configuration.

## Reading traps

- `top level` includes package `__init__` files: a package's own key has no dot.
- Depth is height in the import graph, not architectural layering, and function-level imports inflate it.
- A standalone module is not unused; it means no module imports it. A shell script may still run it.
- A standalone module with routes may not be mounted; check how the server registers it.
- Table rank is breadth (how many modules mention the table), not importance.
- `written by` includes the module that creates a table, so migration and backfill scripts appear in it.
- A list of names inside one line (the modules at a depth, the members of a cycle, the writers or readers of a table,
  the files holding routes) shows only the first few and ends with `, +N` for the rest.
- Counts are exact; a module's role is inferred from its name and title only.
