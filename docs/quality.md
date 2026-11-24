# Checks and tests: how we know the numbers are right

The brief says that the numbers being right matters most. Five things show that they are:

1. **Nothing is lost on the way in.** For every file, the records read equal the records loaded plus the ones quarantined, and every bronze row carries its file, line and checksum.
2. **Every layer adds up.** Silver has one row per bronze row, the fact table has the same rows and credits as silver, and every mart adds up to the fact table. If any of these fails, nothing is written.
3. **Every retired credit traces back to an issuance.** Each retirement and cancellation lies inside one issued batch, and no credit is used twice.
4. **An independent check.** The reference numbers were first worked out from the raw files, before the pipeline existed ([the data analysis](data-analysis.md)). A test holds the pipeline to them.
5. **The same input gives the same bytes,** on macOS and in a Linux container.

## The quality gate

`sql/checks.sql` runs on the finished tables, before anything is written. Each check counts the rows, and the credits, that break its rule; zero passes. The results are kept in `gold.quality_results`, printed by the build and shown on the dashboard.

**6 errors.** Each one means a number would be wrong, so a failure stops the build and nothing is written:

| Check | What it guards against |
|---|---|
| silver has exactly one row per bronze row | a record lost or doubled while cleaning |
| every quantity is a whole number above zero | a total built on a missing, negative or decimal quantity: `12.5` stops the build, it isn't rounded to 13 |
| every row has a project id | credits that belong to no project |
| no serial number appears twice in one export | the same credits counted twice |
| the fact table has the same rows and credits as silver | rows lost or doubled while modelling |
| the marts add up to the fact table | a mart that disagrees with the facts. The marts join the dimensions, so this also proves no event points at a missing project or owner |

**13 warnings.** These are facts about Verra's data. The totals still add up what Verra published, so the build goes on, and the report and the dashboard say what was found:

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

Why two of them are warnings, not errors:
- **Undated retirements** are real retirements, and Verra flags them itself. Leaving them out would understate retired credits by 209,992. They're missing only from charts over time, and the chart says so.
- **Credits retired before their batch was issued** all come from the older registries, whose credits were recorded again when they moved to Verra. An error would block every day's data over a fact about history.

To see the gate's result: `make query SQL="select * from gold.quality_results where not passed"`.

## The integrity rules, and what proves each

| Rule | How it's kept | The test that proves it |
|---|---|---|
| Raw files are only read, and their checksums are recorded | each file is read once, as bytes; its SHA-256 goes into the manifest and onto every bronze row | `test_keeps_values_as_delivered_and_where_each_row_came_from` |
| Only a complete snapshot is loaded | the newest date with all three files | `test_picks_the_newest_complete_snapshot_and_ignores_other_files`; `[missing file]` |
| Parsing survives a byte-order mark, Windows line endings, line breaks inside fields, Windows-1252 and a cut-off last line | the `csv` module, and decoding that reports what it found | `test_loads_every_file_and_reports_its_quirks`, `test_reads_windows_1252_when_a_file_is_not_utf8` |
| Unreadable records go to quarantine, with the reason and exact text, inside a budget counted in lines | `bronze.rejected_records`; `max_rejected_share` | `test_quarantines_the_cut_off_record_with_its_exact_text`; `[one broken quote swallowing the rest]` |
| Headers are matched by name, and a missing required column stops the run | normalised names, aliases in `pipeline.toml` | `test_matches_headers_by_name_in_any_order_and_through_aliases`; `[missing required column]` |
| Every check runs before anything is written, and files are written atomically | one in-memory build; a temporary name, then a rename; the manifest last | `test_a_failed_error_check_stops_the_build_before_anything_is_written`, `test_a_rebuild_hides_its_day_until_every_file_is_written` |
| Every bronze row carries its lineage | `_snapshot_date`, `_source_file`, `_source_line`, `_file_sha256` | `test_keeps_values_as_delivered_and_where_each_row_came_from` |
| The same input gives byte-identical output | one thread, sorted output, no timestamps, pinned versions | `test_a_rebuild_gives_byte_identical_files` |
| Totals reconcile from bronze to silver to gold, and gold is published only when the gate passes | `sql/checks.sql` | `test_gold_adds_up_and_the_gate_reports_what_it_saw`, `test_the_shipped_snapshot_gives_the_reference_numbers` |
| Errors are one clear sentence | one error class, `PipelineError`; a broken SQL file is named | `test_an_error_is_one_clear_line`, `test_a_bad_config_is_one_clear_line`, `test_a_broken_sql_file_is_named_in_one_line` |

The names in brackets are cases of `test_refuses_input_it_cannot_trust_and_writes_nothing`, which feeds six kinds of broken input and checks that each is refused with nothing written.

## The tests

`make check` runs lint, type checks and the 51 tests. GitHub Actions runs it on every push, and also checks the cloud demo's Terraform.

| File | Tests | What they cover |
|---|---|---|
| `tests/test_ingest.py` | 14 | The real files' quirks, on tiny fixture files dated 2030-01-15; headers by name and alias; six kinds of broken input refused with nothing written |
| `tests/test_cli.py` | 5 | The build's report, querying the newest finished snapshot, and one-line errors |
| `tests/test_transform.py` | 19 | Each macro on the formats the files use; owner keys, including a Chinese name and placeholders; the repair of mis-encoded text; totals; the gate failing and writing nothing; the batch checks firing; byte-identical rebuilds; a rebuilt day hidden until it's whole |
| `tests/test_real_snapshot.py` | 1 | Every number in the README's answers, on the shipped snapshot, plus two cleaning rules only real data exercises: the repair of mis-encoded owner names, and each project's most common country |
| `tests/test_dashboard.py` | 8 | The headline numbers equal the model's totals; every view renders, even with no dates or owners; an empty lake says what to do |
| `tests/test_deploy.py` | 4 | The deploy script's dry runs change nothing (`up` and `down` only ask Terraform for its plan), every command names the project, and it refuses to start without one |

**Do the tests catch real mistakes?** The risky lines were mutation-checked: broken on purpose, one at a time, to confirm that a test fails. For example, deleting the line that hides a day during its rebuild makes `test_a_rebuild_hides_its_day_until_every_file_is_written` fail, and reading quantities with a plain cast again makes a test fail.

**Is the build the same everywhere?** Built in the Docker image on Linux, the 15 lake files are identical to the ones built on macOS.
