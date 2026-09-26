# What indextool computes

Every rule in the tables below names, in the right-hand column, the test that pins it. The two prose sections after the
tables ("What the map cannot see" and "Reading traps") describe limits and cite a test only where one pins the claim.
`scripts/check_doc_tests.py` fails CI when a cited test does not exist, so this page cannot silently drift from the
code.

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
| An output path that would overwrite a source or config file (it ends in `.py`, or is named `indextool.toml` or `pyproject.toml`, in any case and directory) is an error, exit 2. | `tests/test_config.py::test_an_output_path_that_would_overwrite_a_source_or_config_file_is_refused` and `tests/test_cli_generate.py::test_an_output_path_that_names_a_source_file_is_a_one_line_error_and_the_file_is_untouched` |

## Modules and import edges

| Rule | Pinned by |
|---|---|
| A module key is its path under a root, dotted; `pkg/__init__.py` is `pkg`. | `tests/test_scan.py::test_module_keys` |
| Roots relativize keys; files outside every root are ignored. | `tests/test_scan.py::test_roots_relativize_keys_and_files_outside_are_ignored` |
| Two files with the same key are an error. | `tests/test_scan.py::test_two_files_with_the_same_key_are_an_error` |
| A test module matches a `tests` pattern and appears only in the module count. | `tests/test_scan.py::test_test_modules_follow_the_tests_patterns` |
| Absolute, relative and submodule imports resolve to the longest known repository module; the rest are dropped. | `tests/test_scan.py::test_edges_absolute_relative_and_submodule_imports` |
| Function-level and conditional imports are edges. | `tests/test_scan.py::test_function_level_and_conditional_imports_are_edges` |
| A file that cannot be decoded or parsed is a module with no imports, and is counted. Its raw text, comments and docstrings included, is its only string literal. A test module that cannot be parsed is counted too but contributes nothing (see [Test modules contribute no facts](#tables-routes-and-io)). | `tests/test_scan.py::test_unparsable_files_are_counted_modules_with_only_their_raw_text` |
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
| In a file that parses, docstrings and comments are not evidence; f-string values stand in as `?`. | `tests/test_facts.py::test_docstrings_and_comments_are_not_evidence_and_fstrings_count` |
| A file that cannot be decoded or parsed contributes its raw text as its only literal, so SQL-looking text in its comments or docstrings can count as evidence for tables, their users and writers. It gets no IO rating and no routes. This holds for a file that is not a test module; an unparsable test module contributes nothing, as the "Test modules contribute no facts" row of this table says. | `tests/test_facts.py::test_an_unparsable_file_contributes_its_raw_text_so_sql_in_a_comment_or_docstring_counts` |
| Table names are escaped and matched longest first. | `tests/test_facts.py::test_custom_create_pattern_and_table_names_are_escaped` |
| Test modules contribute no facts, so an unparsable test module (still counted as "could not be parsed") adds no table, writer, route or IO rating from its raw text. | `tests/test_facts.py::test_test_modules_contribute_nothing` and `tests/test_facts.py::test_an_unparsable_test_module_contributes_nothing` |
| A route is a listed decorator call with a literal first argument starting with `/`. | `tests/test_scan.py::test_routes_require_a_listed_decorator_and_a_literal_path_starting_with_a_slash` |
| The IO rating comes from imports matched by dotted prefix; SQL text alone is not evidence. | `tests/test_facts.py::test_io_rating` |

## Output

| Rule | Pinned by |
|---|---|
| The header carries the title and `indextool <major.minor>`; the numbers section counts what it says. | `tests/test_render.py::test_header_and_numbers` |
| Every capped list of lines ends with a `(+N more)` line (`(+N more packages)`, `(+N more cycles)`, `(+N more route groups)`, `(+N more tables)` and so on), and every capped list of names inside a line ends with `, +N`, with the exact N. | `tests/test_render.py::test_every_cap_prints_its_more_line_and_every_capped_name_list_its_plus_n_with_the_exact_n` |
| A title is cut to its width (70 characters in the map, 90 in the index) and a cut never leaves trailing whitespace: no line of either file ends in a space. | `tests/test_render.py::test_a_title_cut_at_its_width_never_leaves_trailing_whitespace` |
| In the index a pipe character in a title is written as `/`, so that the fields stay unambiguous; the map keeps the title as written. | `tests/test_render.py::test_a_pipe_in_an_index_title_is_written_as_a_slash_so_the_fields_stay_unambiguous` |
| Detector lines and the "cannot say" list come from the active config. | `tests/test_render.py::test_detector_lines_and_cannot_say_reflect_the_config` |
| The "cannot say" list ends with the unparsable-file caveat: such a file contributes its raw text as its only string literal, so SQL-looking text there can count as evidence. | `tests/test_render.py::test_the_closing_list_states_the_unparsable_file_caveat_whatever_the_config` |
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
| `verify` prints at most 12 changed lines per file, then `... (+N more changed lines)` with the exact N. | `tests/test_cli_verify_refresh.py::test_verify_prints_at_most_twelve_changed_lines_and_counts_the_rest` |
| On drift `verify` prints the versions it ran under and, when files failed to parse, a hint to check that CI and local Python versions match. | `tests/test_cli_verify_refresh.py::test_a_drift_with_an_unparsable_file_says_to_check_the_python_versions` |
| `verify` accepts CRLF in the committed map. | `tests/test_cli_verify_refresh.py::test_verify_accepts_crlf_line_endings_in_the_committed_map` |
| `verify --source index` checks what would be committed. | `tests/test_cli_verify_refresh.py::test_index_source_checks_what_would_be_committed` |
| Under `--source index`, an output that is right in the working tree but not staged is reported as such, with `git add <path>` (regenerating would change nothing); an output that is not right there either says to regenerate and then `git add` it. The worktree-mode messages do not change. | `tests/test_cli_verify_refresh.py::test_index_source_checks_what_would_be_committed`, `tests/test_cli_verify_refresh.py::test_index_source_says_to_regenerate_and_stage_when_the_working_tree_copy_is_not_right_either`, `tests/test_cli_verify_refresh.py::test_index_source_says_to_stage_an_output_file_that_exists_on_disk_but_is_not_tracked`, `tests/test_cli_verify_refresh.py::test_index_source_says_to_generate_and_stage_an_output_file_that_exists_nowhere` and `tests/test_cli_verify_refresh.py::test_worktree_mode_keeps_its_messages` |
| Under `--source index`, a pointer block that exists in the working tree but is not staged is reported as such, with `git add <path>`; a stale one says to run `indextool init` and then `git add` it. | `tests/test_cli_verify_refresh.py::test_index_source_says_when_a_pointer_file_is_current_in_the_working_tree_but_not_staged`, `tests/test_cli_verify_refresh.py::test_index_source_says_to_run_init_and_stage_when_the_unstaged_pointer_block_is_out_of_date` and `tests/test_cli_verify_refresh.py::test_index_source_with_no_pointer_block_anywhere_says_to_run_init_and_stage_what_it_writes` |
| A git failure while looking for unstaged files is one warning line and changes neither the verdict nor the exit code; every warning is one line. | `tests/test_cli_verify_refresh.py::test_a_git_failure_while_looking_for_unstaged_files_is_one_warning_line_and_changes_nothing` and `tests/test_cli_verify_refresh.py::test_a_warning_is_always_one_line_even_when_git_says_several` |
| In worktree mode `verify` warns on stderr, without changing its exit code, when files it reads have unstaged changes: CI would see the committed version. The warning watches the tracked Python files, the config and the pointer files (`CLAUDE.md`, `.claude/CLAUDE.md`, `AGENTS.md`). Under `--source index` it never appears. | `tests/test_cli_verify_refresh.py::test_an_unstaged_edit_warns_in_worktree_mode`, `tests/test_cli_verify_refresh.py::test_an_unstaged_edit_of_the_config_warns_in_worktree_mode`, `tests/test_cli_verify_refresh.py::test_an_unstaged_edit_of_a_pointer_file_warns_in_worktree_mode` and `tests/test_cli_verify_refresh.py::test_source_index_never_warns_about_unstaged_config_or_pointer_edits` |
| An untracked config makes `verify` exit 2, naming it. | `tests/test_cli_verify_refresh.py::test_verify_names_an_untracked_config_and_exits_2` |
| `refresh` is silent, fails open and never replaces a good map with an empty one. | `tests/test_cli_verify_refresh.py::test_refresh_never_replaces_a_good_map_with_an_empty_one` |
| `refresh --source index` writes what would be committed, not the unstaged edits. | `tests/test_cli_verify_refresh.py::test_refresh_with_source_index_writes_what_would_be_committed` |
| `refresh` warns on stderr about an untracked config and still writes. | `tests/test_cli_verify_refresh.py::test_refresh_warns_about_an_untracked_config_and_still_writes` |
| A hand-edited pointer block makes `verify` exit 2. | `tests/test_pointer.py::test_verify_exits_2_when_a_block_was_edited_by_hand` |

## The pointer block and `init`

| Rule | Pinned by |
|---|---|
| The pointer goes into `AGENTS.md` when no instruction file exists. When `AGENTS.md` exists and `CLAUDE.md` or `.claude/CLAUDE.md` imports it (a line reading `@AGENTS.md`), the block goes only into `AGENTS.md`. Otherwise it goes into every existing one of `CLAUDE.md`, `.claude/CLAUDE.md` and `AGENTS.md`; an import of an `AGENTS.md` that does not exist redirects nothing, so the block goes into the importing file. | `tests/test_pointer.py::test_placement` |
| A marker counts only as a whole line outside fenced code: a prose mention or a quoted example is not a block. | `tests/test_pointer.py::test_a_prose_mention_of_the_markers_is_not_a_block` and `tests/test_pointer.py::test_a_fenced_example_is_skipped_in_favour_of_the_real_block` |
| Unpaired or duplicate markers are refused, never guessed at: `init` writes nothing and `verify` exits 2 without touching the file. | `tests/test_pointer.py::test_upsert_refuses_an_unpaired_marker_and_returns_nothing_to_write`, `tests/test_pointer.py::test_upsert_refuses_a_second_block` and `tests/test_pointer.py::test_verify_exits_2_on_an_unpaired_marker_and_leaves_the_file_alone` |
| `init` never overwrites an existing config or workflow. | `tests/test_init.py::test_existing_config_is_never_overwritten` and `tests/test_init.py::test_the_workflow_is_not_overwritten` |
| `init` is idempotent, and `--dry-run` writes nothing. | `tests/test_init.py::test_init_is_idempotent` and `tests/test_init.py::test_dry_run_writes_nothing` |
| `init` takes `--config` like the other commands: it reads that file, creates no second config, writes the pointer blocks for that config's output paths, and `verify --config` then passes. | `tests/test_init.py::test_init_takes_the_config_option_the_other_commands_take` and `tests/test_init.py::test_init_dry_run_accepts_config_and_reports_a_missing_config_file_as_exit_2` |
| The config `init` writes records a title: `[project].name` of the base directory's `pyproject.toml`, else the folder name (written once, into the committed config). | `tests/test_init.py::test_init_creates_everything_in_a_fresh_project`, `tests/test_init.py::test_the_written_title_is_the_project_name_of_the_pyproject_when_there_is_one`, `tests/test_init.py::test_the_written_title_is_the_folder_name_of_the_base_directory_without_a_pyproject_name` and `tests/test_init.py::test_the_written_title_is_a_toml_string_whatever_the_name_holds` |
| `init` prints the two commands for other CI systems. | `tests/test_init.py::test_init_prints_the_two_commands_for_other_ci_systems` |
| In a sub-project whose shared workflow already exists but does not run `verify` there, `init` prints the step to add and says the workflow does not check it; the file is not touched. | `tests/test_init.py::test_a_second_sub_project_is_told_that_the_shared_workflow_does_not_check_it`, `tests/test_init.py::test_no_snippet_is_printed_once_the_shared_workflow_names_the_sub_project` and `tests/test_init.py::test_a_project_at_the_top_of_the_repository_is_not_told_about_its_workflow` |
| An output that git ignores is named in a note, because CI cannot verify it. | `tests/test_init.py::test_an_output_git_ignores_is_named_in_a_note_because_ci_cannot_verify_it` and `tests/test_init.py::test_the_note_about_ignored_files_is_for_the_outputs_only` |
| `init` refreshes a stale managed block in every candidate file that already holds one, and adds a block to no other file. | `tests/test_init.py::test_a_stale_block_in_a_file_that_is_not_a_target_is_refreshed_but_no_block_is_added_elsewhere` |
| `init` keeps a CRLF file CRLF and does not rewrite a file that is already up to date. | `tests/test_init.py::test_files_that_use_crlf_keep_it_and_an_up_to_date_file_is_not_rewritten` |
| `init` writes through a symlink, so the link stays a link. | `tests/test_init.py::test_a_symlinked_pointer_file_stays_a_link_and_both_names_show_one_block` |
| Every path `init` prints is relative to the shell directory. | `tests/test_init.py::test_every_printed_path_is_relative_to_the_shell_directory` |

## What the map cannot see

Why a module exists, how modules cooperate beyond importing each other, formulas and thresholds, imports made through
`importlib`, `exec` or `sys.path` changes, tables not created by a matching `CREATE TABLE` in a string literal, routes
not registered by a listed decorator with a literal `/` path, and anything that is not Python source. A file that cannot
be decoded or parsed is read as raw text, which the map also says. Every generated map states this in its closing
section, built from the active configuration.

## Reading traps

- `top level` includes package `__init__` files: a package's own key has no dot.
- Depth is height in the import graph, not architectural layering, and function-level imports inflate it.
- A standalone module is not unused; it means no module imports it. A shell script may still run it.
- A standalone module with routes may not be mounted; check how the server registers it.
- Table rank is breadth (how many modules mention the table), not importance.
- `written by` includes the module that creates a table, so migration and backfill scripts appear in it.
- A list of names inside one line shows only its first names and ends with `, +N` for the rest: 6 modules per depth, 8
  members per cycle or look-alike name, 4 writers and 4 readers per table, 25 files holding routes (pinned by
  `tests/test_render.py::test_every_cap_prints_its_more_line_and_every_capped_name_list_its_plus_n_with_the_exact_n`).
- A file that cannot be decoded or parsed is read as raw text, so an `INSERT INTO` in its comments or docstrings can make
  it a writer of a table, and a `CREATE TABLE` there can add a table. The map counts these files ("could not be
  parsed") and its closing list says so; check that count before trusting a table's writers. A test module that cannot
  be parsed is counted too, but as a test module it contributes nothing.
- Counts are exact; a module's role is inferred from its name and title only.
