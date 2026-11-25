# The data analysis

Before any cleaning was written, every line of the 2026-11-17 files was read and profiled. This page lists what was found, and what each finding changed. Every number here is printed by a script in [`analysis/`](../analysis). The scripts read the files exactly as delivered, and write nothing.

```bash
make analysis                      # every script, in the order of this page (about 5 seconds)
uv run python analysis/owners.py   # just one
```

| Script | Asks |
|---|---|
| `files.py` | Encoding, line endings, records and odd characters, byte by byte |
| `columns.py` | Each column's blanks, distinct values and most common values |
| `dates.py` | Date formats, first and last dates, and undated retirements |
| `vintages.py` | Single years and ranges |
| `serials.py` | What a serial number holds, and how retirements trace back to batches |
| `owners.py` | Blanks, placeholders, spellings, and the ranking before and after cleaning |
| `projects.py` | Whether the files agree on projects and places |
| `reasons.py` | Why credits were retired or cancelled, and multi-value fields |
| `totals.py` | The totals and the 10 largest projects |

They share `analysis/common.py`, which loads the newest files with the pipeline's own reader, as text. A test checks that they still print the key numbers on this page.

## The three files at a glance

| | Issuances | Retirements | Cancellations |
|---|---|---|---|
| Size | 932,183 bytes | 8,311,827 bytes | 131,288 bytes |
| Encoding | UTF-8 | UTF-8, **with a byte-order mark** | UTF-8 |
| Line endings | LF | LF | **CRLF (Windows)** |
| Last line | complete | **cut off, with no final newline** | complete |
| Records | 2,724 | 23,276 (one cut off) | 471 |
| Records over two lines | 0 | **7** | 0 |
| Fields per record | 18 | 20 | 17 |
| One row per | issued batch | retirement | cancellation |

**Each file is the full history,** from 2009, not one day's changes. So each day is rebuilt, not appended.

**The files end on different days:** issuances on 13 Nov 2026, retirements on 16 Nov, cancellations on 31 Mar. Nothing joins them by date: a retirement links to its batch through its serial number.

## Findings, and what they changed

### File format

| Found | What the pipeline does |
|---|---|
| Retirements starts with a byte-order mark, which hides inside the first header | Removes it, and reports it |
| Cancellations uses Windows line endings | Reads them, and reports it |
| The last retirement record is cut off: 9 of its 20 fields | Quarantines it, with its exact text. Its credits can't be known. |
| 7 retirement records hold a line break inside a quoted field | The CSV reader follows the quotes |
| Odd whitespace: 99 no-break spaces, 17 tabs inside fields, and doubled spaces | Silver trims every text value |
| 17 owner names were mis-encoded before export: `StÃ¤dtische` for `Städtische` | Silver repairs 14 of them (8 names). 3 lost a character before export, so they can't be repaired. Real text such as `SÃO PAULO` is left alone. |

### Dates

| Found | What the pipeline does |
|---|---|
| Two formats: `19 Mar 2009`, and `01-Apr-09` in cancellations | `parse_date` reads both. Anything else becomes NULL, and is counted. |
| 19 retirements have no date (209,992 credits). Verra flags them itself. | Kept in every total, and reported |
| 20 retirements are dated before their batch was issued (453,415 credits). All come from older registries (TZ1, MER, CDC, APX), recorded again when they moved to Verra. | Kept, with a warning |
| No date is later than the snapshot | A warning would catch one |

### Vintages

A vintage is the year, or years, in which the reduction happened.

| Found | What the pipeline does |
|---|---|
| A vintage is a year (`2013`) or a range (`2007 - 2008`). Ranges hold 33,573,921 issued credits: 16.9%. | Keeps the label, and adds the first and last year. Charts count a range in its first year, and say so. |
| Every retirement has its batch's vintage | It confirms the batch link below |

### Serial numbers and batches

| Found | What the pipeline does |
|---|---|
| A serial number starts with the batch number, the first serial and the last | `serial_part` reads those three, and ignores the rest |
| On every row, quantity = last − first + 1 | A warning checks it |
| Every retirement and cancellation lies inside exactly one issued batch, and none overlap | Silver keeps `batch_id`, so every retired credit traces back to its issuance. Warnings catch any that don't. |
| A trap: serial ranges repeat, because the old and new numbering overlap. Matching on the range alone gives 34,832 matches for 23,275 retirements. | The match also uses the batch number and the project |

### Owners (question 3)

| Found | What the pipeline does |
|---|---|
| 70.4% of retired credits (39,846,198) name no owner: blank, or a placeholder such as `_`, `-`, `N/A` or `Other` | All become `unspecified`: in the totals, but not in the ranking |
| One owner, many spellings: `BRISBANE CITY COUNCIL`; `Interface, Inc.`, `Interface Inc`, `Interface` | `owner_key` merges them ([how](data-model.md#owner-keys)). The name shown is the spelling with the most credits. |
| The usual "keep only a–z and 0–9" rule erases Chinese names such as `南京玄武环境集团有限公司` | The key keeps letters of every alphabet |
| Some owners are crypto wallets (102 rows), middlemen or codes (`GP-2`) | Kept as delivered |

**The answer to question 3 depends on this cleaning:**

| Rank | As delivered | After cleaning |
|---|---|---|
| 1 | Delta Air Lines, 644,713 | **Interface, Inc., 745,954** (5 spellings) |
| 2 | Interface, Inc., 622,132 | **Brisbane City Council, 712,027** (2 spellings) |
| 3 | GP-2, 553,976 | Delta Air Lines, 644,713 |
| 4 | Brisbane City Council, 536,000 | GP-2, 553,976 |
| 5 | `_` (a placeholder), 496,112 | 0x5298…26e2 (a wallet), 459,247 |

As delivered, there are 3,314 distinct owners. After cleaning, there are 3,200 named owners, plus `unspecified`.

### Projects and places

| Found | What the pipeline does |
|---|---|
| 250 projects. Every project with retirements (110) or cancellations (33) is also in issuances. | `dim_project` holds every project |
| Methodology changes between batches in 9 projects, and one project names three countries | Each project takes its most common details |
| Region doesn't always fit the country: India appears under Africa | Breakdowns use country |
| The country code inside serial numbers is often wrong: Korea carries `KP`, North Korea's code | Country names are kept as delivered |

### Reasons and multi-value fields

| Found | What the pipeline does |
|---|---|
| Retirement Reason is blank on 4,520 rows (25.7 million credits). Cancellation Reason is `Other` or blank. | Kept as delivered |
| Commas separate the values of scopes and methodologies, but single values contain commas too | Kept as text |

## Reference numbers

Worked out from the raw files first. `tests/test_real_snapshot.py` holds the pipeline to them.

**Totals:** 250 projects; 198,511,826 credits issued; 56,564,196 retired; 6,123,377 cancelled; 135,824,253 available (68.4% of issued).

**The 10 largest projects by credits issued**

| Project | Issued | Retired | Cancelled | Available |
|---|---|---|---|---|
| 1477 Katingan Peatland Restoration and Conservation | 49,594,403 | 0 | 0 | 49,594,403 |
| 92 300MW Hydropower project by JHPL | 18,508,520 | 10,579,355 | 124,818 | 7,804,347 |
| 4150 DelAgua Clean Cooking Grouped Project in Rwanda | 9,814,801 | 0 | 2,906,291 | 6,908,510 |
| 438 Grouped Hydropower Plants in Chongqing, Yunnan, … | 7,318,432 | 7,176,961 | 0 | 141,471 |
| 1728 Bundled Wind Power Project by Mytrah Group | 6,030,640 | 0 | 0 | 6,030,640 |
| 766 Teesta-V Hydro Power project in Sikkim | 5,616,600 | 2,063,312 | 550,000 | 3,003,288 |
| 1408 Chyulu Hills REDD+ Project | 5,172,697 | 0 | 0 | 5,172,697 |
| 93 86 MW Hydro Project in Himachal Pradesh | 4,067,306 | 2,876,764 | 743,919 | 446,623 |
| 1201 Gola REDD project | 3,513,782 | 0 | 0 | 3,513,782 |
| 717 CECIC HKC Gansu Changma Wind Power project | 3,159,174 | 2,649,826 | 0 | 509,348 |

**The 10 largest retirers, and what they retire**

| Owner | Credits | Mostly from |
|---|---|---|
| Interface, Inc. | 745,954 | 717 Gansu Changma wind |
| Brisbane City Council | 712,027 | 438 Chongqing hydropower, 717 Gansu wind |
| Delta Air Lines | 644,713 | 717 Gansu wind, all of it |
| GP-2 | 553,976 | 837 Kothapeta gas power, 688 Wayang Windu geothermal, 92 JHPL hydro |
| 0x5298…26e2 (a wallet) | 459,247 | 513 Salto Pilão hydropower, all of it |
| Clients of Ausante | 325,770 | 766 Teesta-V hydro, all of it |
| Städtische Werke AG, Kassel | 299,776 | 93 Himachal hydro, 693 Erkenek hydro |
| GP-4 | 299,674 | 688 Wayang Windu geothermal, 766 Teesta-V hydro |
| Pangolin | 227,942 | 92 JHPL hydro, plus 8 other projects |
| Rémy Cointreau | 220,692 | 438 Chongqing hydropower, all of it |

Almost all of their credits come from big hydro, wind and gas power projects in India and China. The wallet's come from a Brazilian hydropower project.

### Check it yourself

After `make build`, compare with what the pipeline built, using `make query` or the SQL page:

```bash
# undated retirements: 19 rows, 209,992 credits
make query SQL="select count(*) as rows, sum(quantity) as credits from gold.fct_credit_event where event_type = 'retirement' and event_date is null"

# the ranking as delivered, straight from bronze: Delta first, the placeholder _ fifth
make query SQL="select beneficial_owner, sum(retirement_qty::bigint) as credits from bronze.retirements where trim(beneficial_owner) <> '' group by all order by credits desc limit 5"

# the ranking after cleaning
make query SQL="select distinct owner_rank, owner_name, owner_credits from gold.mart_top_retirers where owner_rank <= 5 order by owner_rank"
```

## Left alone, on purpose

- **Owner names in the retirement details.** 1,214 retirements with a blank owner say who they were for there ("on behalf of …"). 51 name Interface, for 1,114,109 credits. Free text needs real language handling.
- **Splitting multi-value fields,** until there's a list of the known values.
- **Standard country codes,** and state spellings (`Tamilnadu`, `Tamil Nadu`).
- **Owners whose names differ by more** than case, accents, punctuation or a final legal form, such as two spellings of Chevron with the legal form in the middle.
- **Spreading multi-year vintages across their years:** the files don't say how.
