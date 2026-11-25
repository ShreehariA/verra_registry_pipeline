# Checks and tests

The brief says the numbers being right matters most. This page shows how we know they are.

## Why the numbers can be trusted

1. **Nothing is lost on the way in.** For every file, the records read equal the records loaded plus the ones quarantined. Every bronze row keeps its file, line and checksum.
2. **Every layer adds up.** Silver has one row per bronze row, the fact table matches silver, and every mart adds up to the fact table.
3. **Every retired credit traces back to an issuance.** Each retirement and cancellation lies inside one issued batch, and no credit is used twice.
4. **The numbers were worked out twice.** The [data analysis](data-analysis.md) found them first, with its own SQL, and a test holds the pipeline to them. They share only the file reader, which `analysis/files.py` checks byte by byte.
5. **The same input gives the same output:** the same bytes on the same machine, and the same data, row for row, on Google Cloud.

## The quality gate

`sql/checks.sql` runs on the finished tables, before anything is written. Each check counts the rows and credits that break its rule, and zero means it passed. The results go to `gold.quality_results`, the build's report and the dashboard.

**6 errors** stop the build, because a number would be wrong:

| Check | Guards against |
|---|---|
| silver has exactly one row per bronze row | a record lost or doubled while cleaning |
| every quantity is a whole number above zero | a total built on a bad quantity: `12.5` stops the build instead of becoming 13 |
| every row has a project id | credits that belong to no project |
| no serial number appears twice in one export | the same credits counted twice |
| the fact table has the same rows and credits as silver | rows lost or doubled while modelling |
| the marts add up to the fact table | a mart that disagrees with the facts, or an event pointing at a missing project or owner |

**13 warnings** are facts about Verra's data. The build goes on, and says what it found:

| Check | Today |
|---|---|
| records quarantined: unreadable lines in the raw files | 1 record |
| events with no readable date | 19 rows, 209,992 credits |
| dates before 2008 or after the snapshot date | 0 |
| serial numbers that could not be read | 0 |
| vintages that could not be read | 0 |
| quantity differs from the size of the serial range | 0 |
| retired or cancelled credits outside every issued batch | 0 |
| retired or cancelled before the batch was issued | 20 rows, 453,415 credits |
| credits retired or cancelled twice (overlapping serial ranges) | 0 |
| batches with more retired and cancelled than issued | 0 |
| projects with a negative available balance | 0 |
| projects with retirements or cancellations but no issuance | 0 |
| retired credits with no named owner | 7,390 rows, 39,846,198 credits |

Two of them look like errors, but aren't:
- **Undated retirements** are real, and Verra flags them itself. Leaving them out would understate retired credits by 209,992.
- **Credits retired before their batch was issued** all come from older registries, whose credits were recorded again when they moved to Verra.

See today's result: `make query SQL="select * from gold.quality_results where not passed"`.

## The integrity rules, and the test for each

| Rule | The test that proves it |
|---|---|
| Raw files are only read, and their checksums are recorded | `test_keeps_values_as_delivered_and_where_each_row_came_from` |
| Only a complete snapshot is loaded | `test_picks_the_newest_complete_snapshot_and_ignores_other_files`, `[missing file]` |
| Parsing survives a byte-order mark, Windows line endings, line breaks inside fields, Windows-1252 and a cut-off last line | `test_loads_every_file_and_reports_its_quirks`, `test_reads_windows_1252_when_a_file_is_not_utf8` |
| Unreadable records go to quarantine, inside a budget counted in lines | `test_quarantines_the_cut_off_record_with_its_exact_text`, `[one broken quote swallowing the rest]` |
| Headers are matched by name, and a missing required column stops the run | `test_matches_headers_by_name_in_any_order_and_through_aliases`, `[missing required column]` |
| Every check runs before anything is written, and files are written atomically | `test_a_failed_error_check_stops_the_build_before_anything_is_written`, `test_a_rebuild_hides_its_day_until_every_file_is_written` |
| Every bronze row carries its lineage | `test_keeps_values_as_delivered_and_where_each_row_came_from` |
| The same input gives byte-identical output | `test_a_rebuild_gives_byte_identical_files` |
| Totals reconcile, and gold is published only when the gate passes | `test_gold_adds_up_and_the_gate_reports_what_it_saw`, `test_the_shipped_snapshot_gives_the_reference_numbers` |
| Errors are one clear sentence | `test_an_error_is_one_clear_line`, `test_a_bad_config_is_one_clear_line`, `test_a_broken_sql_file_is_named_in_one_line` |

The names in brackets are cases of `test_refuses_input_it_cannot_trust_and_writes_nothing`. It feeds in six kinds of broken input, and checks that each is refused with nothing written.

## The tests

`make check` runs the linters, the type checker and 70 tests. GitHub Actions runs the same on every push to main and every pull request, and checks the Terraform too. It deploys nothing.

```bash
make check                                 # everything, as CI runs it
uv run pytest tests/test_transform.py -v   # one file, each test by name
uv run pytest -k rebuild                   # only tests with "rebuild" in their name
```

| File | Tests | Covers |
|---|---|---|
| `test_ingest.py` | 14 | The real files' quirks, on tiny sample files; headers by name and alias; six kinds of broken input |
| `test_cli.py` | 5 | The build's report, `verra query`, and one-line errors |
| `test_transform.py` | 19 | Every macro and owner key; repairing mis-encoded names; totals; a failed gate writing nothing; the batch checks; byte-identical rebuilds |
| `test_real_snapshot.py` | 2 | Every number in the README's answers, on the real files; the analysis scripts still print the numbers the docs quote |
| `test_dashboard.py` | 26 | Every page renders, even with no dates or owners; the figures match the model; search, picking a row, and the SQL page; SQL typed by anyone can't touch a file or run forever |
| `test_deploy.py` | 4 | The deploy script's dry runs change nothing, and every command names the project |

**Do the tests catch real mistakes?** The risky lines were broken on purpose, one at a time, to confirm that a test fails. For example, deleting the line that hides a day while it's rebuilt makes `test_a_rebuild_hides_its_day_until_every_file_is_written` fail.
