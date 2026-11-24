# Data analysis: what the three files really contain

Before any cleaning was written, every line of the 2026-11-17 snapshot was read and profiled. This page lists what was found, and the decision each finding led to. The numbers come from bronze, which holds every value exactly as delivered, with its file and line; [Check it yourself](#check-it-yourself) reproduces the key ones.

**Contents**
1. [How the files were read](#how-the-files-were-read)
2. [The three files at a glance](#the-three-files-at-a-glance)
3. [Findings, and what they changed](#findings-and-what-they-changed)
4. [Reference numbers](#reference-numbers)
5. [Left alone, on purpose](#left-alone-on-purpose)

## How the files were read

Two passes:
1. **Bytes and lines:** the encoding, the byte-order mark and the line endings; unusual characters (no-break spaces, tabs, zero-width spaces, mis-encoded text); the number of fields in each record; records that run over several lines.
2. **Values:** each column's blanks, distinct values and most common values. Then one question at a time: dates, vintages, serial numbers, how the files link, projects, owners, reasons and places.

## The three files at a glance

| | Issuances | Retirements | Cancellations |
|---|---|---|---|
| Size | 932,183 bytes | 8,311,827 bytes | 131,288 bytes |
| Encoding | UTF-8 | UTF-8, **with a byte-order mark** | UTF-8 |
| Line endings | LF | LF | **CRLF (Windows)** |
| Last line | complete | **cut off, with no final newline** | complete |
| Records | 2,724 | 23,276 (one of them cut off) | 471 |
| Records over two lines | 0 | **7** | 0 |
| Fields per record | 18 | 20 | 17 |
| One row per | issued batch | retirement | cancellation |

**Each file is the full history, not one day's changes.** All three start in 2009. So each day's drop replaces the last one: the pipeline rebuilds a snapshot rather than appending to yesterday's.

**The files don't end on the same day.** The newest issuance is dated 13 Nov 2026, the newest retirement 16 Nov 2026, and the newest cancellation 31 Mar 2026. Nothing joins the files by date: a retirement links to its issued batch through its serial number (below). If a retirement ever arrived before the issuance of its batch, the warning "retired or cancelled credits outside every issued batch" would count it.

## Findings, and what they changed

### File format

| Found | What the pipeline does |
|---|---|
| Retirements starts with a byte-order mark. Read naively, the first header becomes an invisible character plus `Program`, and no longer matches by name. | Bronze removes the mark and reports it. |
| Cancellations uses Windows line endings. | Read like the others, and reported. |
| The last retirement record is cut off: 9 of 20 fields, with no serial number and no quantity. | Quarantined with its exact text and the reason. It's 1 line in 23,283, far inside the 1% budget. Its credits can't be known, so no total includes them. |
| 7 retirement records hold a line break inside a quoted field: Portuguese text, then the English. A reader that splits on line breaks makes 14 broken records of them. | The CSV reader follows the quotes, and each record keeps the line it starts on. |
| Odd whitespace in retirements: 99 no-break spaces, 17 tabs inside fields (`Yan<tab>Liu`), and spaces before, after and doubled inside owner names. | Bronze keeps it all. Silver trims every text value, and makes every run of whitespace one space. |
| 17 owner names were mis-encoded before Verra exported them: `StÃ¤dtische Werke AG` for `Städtische Werke AG`. The file itself is valid UTF-8, so no choice of encoding fixes it. | Silver repairs owner names: it encodes the text as Windows-1252 and decodes it as UTF-8, keeping the original when that fails. Genuine text such as `SÃO PAULO` stays as it is. |

### Dates

| Found | What the pipeline does |
|---|---|
| Two date formats: `19 Mar 2009` in issuances and retirements, `01-Apr-09` in cancellations. | `parse_date` reads both. Anything else becomes NULL, and the quality gate counts it. |
| 19 retirements have no date (209,992 credits). Verra flags them itself: `FLAG`, "missing Retirement Date". | Kept in every total, shown as "undated" in charts over time, and reported as a warning. |
| 20 retirements are dated before their batch was issued (453,415 credits, up to 350 days earlier). All come from batches of the older registries (TZ1, MER, CDC, APX), most likely recorded again when they moved to Verra. | Kept, with a warning. It isn't an error, because the numbers are still right. |
| No date is later than the snapshot. | A warning catches dates before 2008 or after the snapshot date in later drops. |

### Vintages

The vintage is the year, or years, in which the emission reduction happened.

| Found | What the pipeline does |
|---|---|
| A vintage is one year (`2013`) or a range (`2007 - 2008`, from 2 to 9 years). Ranges hold 33,573,921 issued credits: 16.9%. | Silver keeps the label and adds `vintage_start` and `vintage_end`. Charts by year count a range in its first year, and say so: the files don't say how a range splits. |
| The vintage matches the monitoring period at the end of the serial number on every row but one, and every retirement has the vintage of its batch. | Nothing to fix. It confirms the batch link below. |

### Serial numbers and batches

| Found | What the pipeline does |
|---|---|
| Serial numbers come in an older and a newer family, with different middle parts; sometimes a middle part is missing. The batch number, the first serial and the last serial always come first. | `serial_part` reads only the start, with an anchored pattern, never by position. |
| On every row, the quantity equals the last serial minus the first, plus 1. | A warning check: "quantity differs from the size of the serial range". |
| The first number is the issuance batch. Every one of the 23,275 retirements and 471 cancellations lies inside exactly one issued batch, no two overlap, and no batch is used more than it was issued. | Silver and the fact table keep `batch_id`. Warning checks catch credits outside every batch, credits used twice, and a batch used more than issued. So every retired credit traces back to an issuance. |
| A trap: serial ranges repeat across the registry, because the old and new numbering overlap. Matching on the range alone gives 34,832 matches for 23,275 retirements. | The match always includes the batch number and the project. |

### Owners (question 3)

| Found | What the pipeline does |
|---|---|
| 70.4% of retired credits name no owner (39,846,198 credits): the field is blank, or a placeholder such as `_` (496,112 credits, enough to rank 5th), `-`, `N/A` or `Other`. | All of them become `unspecified`: kept in the totals, left out of the ranking, and stated on the dashboard. |
| One owner is often written several ways: in capitals (`BRISBANE CITY COUNCIL`), with or without punctuation and legal form (`Interface, Inc.`, `Interface Inc`, `Interface`), mis-encoded, or a wallet address in two cases. | `owner_key` merges them (see [the data model](data-model.md#owner-keys)). The name shown is the spelling with the most credits, and the dashboard lists every spelling merged. |
| The usual "keep only a–z and 0–9" rule turns Chinese company names into nothing: `南京玄武环境集团有限公司` would join the blanks. | The key keeps letters of every alphabet. |
| Owners aren't always end users. 102 rows name a crypto wallet, some name intermediaries (`Clients of Ausante`), and some are codes (`GP-2`). | Kept as names, as delivered. |

**The answer to question 3 depends on this cleaning:**

| Rank | As delivered | After cleaning |
|---|---|---|
| 1 | Delta Air Lines, 644,713 | **Interface, Inc., 745,954** (5 spellings) |
| 2 | Interface, Inc., 622,132 | **Brisbane City Council, 712,027** (2 spellings) |
| 3 | GP-2, 553,976 | Delta Air Lines, 644,713 |
| 4 | Brisbane City Council, 536,000 | GP-2, 553,976 |
| 5 | `_` (a placeholder), 496,112 | 0x5298…26e2 (a wallet), 459,247 |

As delivered, a placeholder ranks 5th. Each cleaning step merges a few more spellings: 3,314 distinct owners as delivered, 3,200 named owners after the owner key, plus `unspecified`.

### Projects and places

| Found | What the pipeline does |
|---|---|
| The files agree on projects: 250 in issuances, and every project with retirements (110) or cancellations (33) is also in issuances. | `dim_project` holds every project found in any export. |
| Methodology changes between batches in 9 projects (usually a new version), and one project's batches name three countries. | Each project takes its most common combination of details. Ties go to the alphabetically first, so a rebuild picks the same one. |
| Region doesn't always fit the country: India appears under Africa, and Turkey under both Asia and the Middle East. Region is blank on 446 rows. | Breakdowns by place use country. Region is kept, but never relied on. |
| The 2-letter country code inside the serial number is often wrong: Korea carries `KP` (North Korea's code), and 11 Turkey rows carry `TM` (Turkmenistan). | Country names are kept as delivered. Standard codes are in "What's next". |

### Reasons and multi-value fields

| Found | What the pipeline does |
|---|---|
| Retirement Reason is blank on 4,520 rows, which hold the most credits of any reason (25.7 million). Cancellation Reason is `Other` or blank, and its details are always blank. | Kept as delivered. The data can't say why credits were cancelled. |
| Commas separate the values of scopes, methodologies, labels and goals, but single values contain commas too: `Fugitive emissions from fuels (solid, oil and gas)`. | Kept as text. Splitting them needs a list of the known values. |

## Reference numbers

These were worked out from the raw files first; `tests/test_real_snapshot.py` holds the pipeline to them.

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

Almost all of the largest retirers' credits come from big hydro, wind and gas power projects in India and China. The exception is the wallet, whose credits come from a Brazilian hydropower project.

### Check it yourself

After `make build`:

```bash
# the undated retirements: 19 rows, 209,992 credits
make query SQL="select count(*) as rows, sum(quantity) as credits from gold.fct_credit_event where event_type = 'retirement' and event_date is null"

# the owner ranking as delivered, straight from bronze: Delta Air Lines first, the placeholder _ fifth
make query SQL="select beneficial_owner, sum(retirement_qty::bigint) as credits from bronze.retirements where trim(beneficial_owner) <> '' group by all order by credits desc limit 5"

# the same ranking after cleaning
make query SQL="select distinct owner_rank, owner_name, owner_credits from gold.mart_top_retirers where owner_rank <= 5 order by owner_rank"
```

## Left alone, on purpose

- **Owner names written in Retirement Reason Details.** 1,214 retirements with no owner say "on behalf of …" there, for example "Retired for Interface Inc. 2009 Cool Carpet Program". Free text needs real language handling.
- **Splitting multi-value fields,** until there's a list of the known values.
- **Standard country codes, and state spellings** (`Tamilnadu` and `Tamil Nadu`).
- **Owners whose names differ by more** than case, accents, punctuation or a final legal form. `Chevron Petroleum Company S.A NIT 860.005.223-9` and `CHEVRON PETROLEUM COMPANY NIT 860005223-9` stay apart, because the legal form sits in the middle.
- **Spreading multi-year vintages across their years:** the files don't say how a range splits.
