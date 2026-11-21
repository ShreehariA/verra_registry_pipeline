# schema/: what every table looks like

There is one JSON file per table, in one folder per layer. The pipeline reads these files on start-up. No table or column is defined in Python: to add, remove or rename a column, you edit JSON here.

```
schema/
  shared/bronze_lineage.json     columns several tables share, pulled in with "include"
  bronze/issuances.json          one file per table: schema/<layer>/<table>.json
  bronze/retirements.json
  bronze/cancellations.json
  bronze/rejected_records.json   the quarantine table of the verra source system
  silver/ ...                    step 3 (3NF tables with primary and foreign keys)
  gold/ ...                      step 4 (star schema and summary tables)
```

The rules every file must follow live with the code, in [`src/verra_pipeline/formats/`](../src/verra_pipeline/formats/) (JSON Schema). Each file points at its rules with `"$schema"`, so VS Code and other editors autocomplete the keys and underline mistakes as you type.

See what is declared:

```bash
uv run verra schema                        # every table
uv run verra schema --table retirements    # one table's columns, with where each value comes from
```

## A table file

```json
{
  "$schema": "../../src/verra_pipeline/formats/table.schema.json",
  "layer": "bronze",
  "name": "retirements",
  "description": "Every readable row of VerraRetirements_<date>.csv, values exactly as delivered.",
  "grain": "One row per record in the file.",
  "source": { "system": "verra", "file_prefix": "VerraRetirements" },
  "columns": [
    { "name": "retirement_qty", "type": "text", "source_header": "Retirement QTY", "required": true,
      "description": "Number of credits retired in this record, as delivered." }
  ],
  "include": ["bronze_lineage"]
}
```

**Table keys**

| Key | Needed | Meaning |
|---|---|---|
| `layer` | yes | `bronze`, `silver` or `gold`; must match the folder |
| `name` | yes | must match the file name |
| `description` | yes | what the table holds |
| `grain` | no | what one row means |
| `source` | bronze | `system` is the source system as named in `config/pipeline.json`. `file_prefix` names the file the table is loaded from; the quarantine table names only its system |
| `role` | bronze | `"quarantine"` marks the table that receives the system's unreadable records |
| `unknown_columns` | bronze | `"keep"` (default) or `"drop"`: what happens to a column the file has but the table does not declare |
| `columns` | yes | the table's own columns, in output order |
| `include` | no | shared column sets from `shared/`, added after the table's own columns |
| `primary_key`, `foreign_keys` | silver, gold | the columns that identify a row, and the columns that must match a row in another table |

**Column keys**

| Key | Needed | Meaning |
|---|---|---|
| `name` | yes | lower-case snake_case |
| `type` | yes | `text`, `integer` (64-bit), `double`, `boolean` or `date` |
| `description` | yes | what the value means |
| `nullable` | no | default `true`; `false` makes an empty value an error |
| `source_header` | bronze | the header in the file that feeds this column |
| `aliases` | bronze | other headers accepted for it, e.g. after Verra renames one |
| `required` | bronze | the file must have this column, or the run stops |
| `generated` | no | a value the pipeline fills in: `snapshot_date`, `source_file`, `source_line`, `file_sha256`, `target_table`, `line_count`, `reject_reason` or `raw_text` |

Headers are matched by name, never by position, after normalising: case, spaces and punctuation do not matter. A reordered file therefore still loads.

## Common changes (no code change needed)

| You want to | Do this |
|---|---|
| Accept a header Verra renamed | Add the new header text to the column's `aliases` |
| Load a column Verra added | Add a column entry with its `source_header`. Until you do, it is still loaded: kept at the end as text and reported, never lost |
| Stop loading a column | Delete its entry **and** set `"unknown_columns": "drop"` on the table. Without `drop` the column is kept at the end and reported, because bronze never silently loses delivered data |
| Make a column mandatory | Set `"required": true`. A file without it then stops the run |
| Add another export from the same system | Add `bronze/<table>.json` with its `source.file_prefix`; every snapshot is then expected to include that file |
| Add another source system | Add it under `sources` in `config/pipeline.json`, then add its bronze tables (with `source.system`) and one quarantine table |
| Share columns between tables | Put them in `shared/<set>.json` and add the set's name to each table's `include` |

## How the files are checked

On every run:
1. **Format:** each file must follow its JSON Schema.
2. **Cross-checks:**
   - The name matches the file, and the layer matches the folder.
   - No column repeats once includes are added, and every include exists.
   - Every header feeds exactly one column.
   - Only bronze reads files, and bronze declares no keys.
   - Each source system has exactly one quarantine table.
   - Key columns exist, and foreign keys point at real tables.

Any problem stops the run with the file and the reason, for example:

```
error: bronze/retirements.json: columns/0/type: 'strng' is not one of ['text', 'integer', 'double', 'boolean', 'date']
```

Every run's manifest also records a **schema fingerprint**: a checksum of all the table definitions. So you can always tell which version of these files produced a given partition.
