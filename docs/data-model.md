# The data model

[The README](../README.md#the-data-model) shows the star schema, and each table's grain, key and relations. This page explains how each value is made, from the text Verra delivers to the three answers.

## Silver: every value read, nothing dropped

Silver has one table per export, with one row per bronze row. It reads only the columns that `pipeline.toml` lists. A value that can't be read becomes NULL, and the quality gate counts every kind of NULL, so nothing unreadable passes silently.

The reading rules are small SQL functions (macros) in `sql/macros.sql`:

| Macro | Reads | Gives |
|---|---|---|
| `whole_number` | quantities and project IDs | digits only, else NULL. A plain cast isn't enough: it reads `12.5` as 13 and `1e3` as 1000 without a word |
| `parse_date` | `19 Mar 2009`, `01-Apr-09` (00–68 is 2000–2068) or `2009-03-19` | a date, else NULL |
| `vintage_start`, `vintage_end` | `2013`, or a range such as `2007 - 2008` | the first year and the last year |
| `serial_part` | the start of a serial number: `10026-172542403-172547402-…` | the batch number, the first serial and the last serial |
| `clean_text` | every text column: names, places, vintages, owners | trimmed, every run of spaces, tabs and no-break spaces made one space; blank becomes NULL |
| `owner_key` | owner names | one key per owner, whatever the spelling (below) |

One rule runs in Python, because DuckDB can't re-encode text: `transform.repair` mends owner names that were mis-encoded before Verra exported them (`StÃ¤dtische` becomes `Städtische`). It keeps the original whenever the repair fails, so genuine text is never changed.

Each silver table has the project's details (name, scope, methodology, region, country, state), the vintage and its two years, the serial number with `batch_id`, `serial_first` and `serial_last`, the date, the quantity, and the lineage columns `_source_file` and `_source_line`. Retirements also have the owner's name and `owner_key`.

## Owner keys

`owner_key` makes one owner of many spellings:
1. lower case, with accents removed;
2. anything but a letter or a digit becomes a space. Letters of every alphabet count, so a Chinese company name survives;
3. blanks and placeholders (`_`, `-`, `N/A`, `None`, `Other`, `Unknown`) become `unspecified`;
4. a legal form at the end is dropped (Inc, Ltd, GmbH, S.A., Corp and others), then the spaces.

So `Interface, Inc.`, `Interface Inc` and `INTERFACE` are all `interface`. Names that differ by more stay apart, on purpose: a fuzzy match is hard to explain, and it can merge two different companies.

## Gold: the star

**`fct_credit_event`** stacks the three silver tables: one row per issuance, retirement or cancellation, keyed by `event_type` and `serial_number`. Every credit total is a sum of `quantity`. A retirement or cancellation has the same `batch_id` and `project_id` as the issuance its credits came from, and its serial range lies inside that issuance's range. `owner_key` is set on retirements only.

**`dim_project`** holds every project found in any export. Name, scope, region and state are the same on every row of a project. Methodology and country can change from batch to batch, so each project takes its most common combination of details; ties go to the alphabetically first, so a rebuild picks the same one.

**`dim_beneficial_owner`** has one row per `owner_key`. `owner_name` is the spelling with the most credits, and `spellings` lists every spelling merged, so a reader can check the merge. `unspecified` holds the blank and placeholder owners.

## Gold: one mart per question

| Mart | One row per | How it's made |
|---|---|---|
| `mart_project_balance` (Q1) | project | `issued`, `retired` and `cancelled` are sums of `quantity` by event type; `available` = issued − retired − cancelled. With the project's name, country and scope. |
| `mart_vintage_activity` (Q2) | vintage, as Verra writes it | The same sums per vintage, with `vintage_start`, `vintage_end` and the number of projects. A chart by year counts a range in its first year, and says so. |
| `mart_top_retirers` (Q3) | owner and project | Credits, retirements, vintages and first and last dates for each owner and project. `owner_rank` ranks the named owners by everything they retired. `unspecified` has no rank, but stays in the totals. |
| `quality_results` | quality check | What the gate measured on this snapshot: failing rows and credits, and whether the check passed. |

The quality gate checks that every mart adds up to the fact table, and the marts join both dimensions. So no event can point at a missing project or owner without the build stopping.

## Example queries

After `make build`:

```bash
make query SQL="select * from gold.mart_project_balance order by issued desc limit 5"
make query SQL="select vintage, issued, retired, cancelled from gold.mart_vintage_activity order by vintage_start, vintage_end"
make query SQL="select owner_name, project_name, credits from gold.mart_top_retirers where owner_rank = 1 order by credits desc"
make query SQL="select owner_name, spellings from gold.dim_beneficial_owner where owner_key = 'interface'"
```
