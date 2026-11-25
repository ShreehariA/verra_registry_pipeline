# The data model

[The README](../README.md#the-data-model) shows the tables, their keys and how they relate. This page shows how each value is made.

## Silver: every value read, no row dropped

Silver has one table per file, and one row per bronze row. A value that can't be read becomes NULL, and the quality gate counts it.

The reading rules are small SQL functions (macros) in `sql/macros.sql`:

| Macro | Reads | Gives |
|---|---|---|
| `whole_number` | quantities and project IDs | the number if it's only digits, else NULL. A plain cast would quietly read `12.5` as 13. |
| `parse_date` | `19 Mar 2009`, `01-Apr-09` or `2009-03-19` | a date, else NULL |
| `vintage_start`, `vintage_end` | `2013`, or a range such as `2007 - 2008` | the first and the last year |
| `serial_part` | a serial number: `10026-172542403-172547402-…` | the batch number, the first serial and the last |
| `clean_text` | every text column | trimmed, with runs of spaces made one. Blank becomes NULL. |
| `owner_key` | owner names | one key per owner, whatever the spelling |

One rule is Python, because DuckDB can't re-encode text: `transform.repair` mends owner names that were mis-encoded before Verra exported them (`StÃ¤dtische` becomes `Städtische`). If a repair fails, the name stays as it was.

## Owner keys

`owner_key` turns many spellings into one owner:
1. lower case, without accents;
2. anything but a letter or a digit becomes a space. Letters of every alphabet count, so Chinese names survive;
3. blanks and placeholders (`_`, `-`, `N/A`, `None`, `Other`, `Unknown`) become `unspecified`;
4. a legal form at the end (Inc, Ltd, GmbH, S.A., Corp and others) is dropped.

So `Interface, Inc.`, `Interface Inc` and `INTERFACE` are all `interface`. Names that differ more stay apart on purpose: fuzzy matching is hard to explain, and it can merge two different companies.

## Gold: the star

- **`fct_credit_event`:** the three silver tables stacked, one row per event. A retirement or cancellation has the same `batch_id` and `project_id` as the issuance its credits came from, and its serials lie inside that issuance's range.
- **`dim_project`:** every project. Methodology and country can change between batches, so each project takes its most common details. Ties go to the first alphabetically, so a rebuild picks the same.
- **`dim_beneficial_owner`:** one row per `owner_key`. `owner_name` is the spelling with the most credits, and `spellings` lists every spelling merged, so you can check the merge.

## Gold: one table per question

| Table | One row per | Holds |
|---|---|---|
| `mart_project_balance` | project | issued, retired, cancelled, and available = issued − retired − cancelled |
| `mart_vintage_activity` | vintage | the same sums per vintage, with its first and last year |
| `mart_top_retirers` | owner and project | credits, vintages and dates. `owner_rank` ranks the named owners; `unspecified` has no rank, but stays in the totals. |
| `quality_results` | quality check | what the gate measured, and whether the check passed |

The marts join both dimensions, and the gate checks that they add up to the fact table. So an event pointing at a missing project or owner stops the build.

## Try it

```bash
make query SQL="select * from gold.mart_project_balance order by issued desc limit 5"
make query SQL="select vintage, issued, retired, cancelled from gold.mart_vintage_activity order by vintage_start, vintage_end"
make query SQL="select owner_name, project_name, credits from gold.mart_top_retirers where owner_rank = 1 order by credits desc"
make query SQL="select owner_name, spellings from gold.dim_beneficial_owner where owner_key = 'interface'"
```
