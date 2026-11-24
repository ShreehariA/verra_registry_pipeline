"""The SQL workspace, after DBeaver: a navigator of every table, an editor with examples and a history,
each table's columns, profile and rows, and the star schema. Every query runs on its own locked-down copy
(common.run_sql)."""

import re

import duckdb
import streamlit as st
from common import MAX_ROWS, SECONDS, number, run_sql, snapshot

lake, manifest, data = snapshot()
catalog = data["catalog"]
EXAMPLES = {
    "Largest projects": "SELECT project_name, issued, retired, cancelled, available\n"
    "FROM gold.mart_project_balance\nORDER BY issued DESC\nLIMIT 10",
    "Raw retirement lines": "SELECT _source_file, _source_line, beneficial_owner, retirement_qty\n"
    "FROM bronze.retirements\nLIMIT 20",
    "Undated retirements": "SELECT *\nFROM gold.fct_credit_event\n"
    "WHERE event_type = 'retirement' AND event_date IS NULL",
    "Owners with several spellings": "SELECT owner_name, spellings\nFROM gold.dim_beneficial_owner\n"
    "WHERE spellings LIKE '%|%'\nORDER BY owner_name",
    "Quality checks": "SELECT *\nFROM gold.quality_results\nORDER BY passed, severity",
}


def load(sql: str) -> None:
    """Put a query in the editor, run it, and show it."""
    st.session_state.sql_text = sql
    st.session_state.sql_pending = True
    st.session_state.sql_tab = "Query"


def pick_example() -> None:
    if st.session_state.sql_example:
        load(EXAMPLES[st.session_state.sql_example])
    st.session_state.sql_example = None  # the chips load a query; they don't stay selected once it's edited


def execute(sql: str, explain: bool) -> None:
    """Run a query, keep its result for the page, and put it first in the history, with one status line."""
    try:
        frame, ms = run_sql(lake, f"EXPLAIN {sql}" if explain else sql)
        error, status = None, f"{len(frame):,} row{'s' * (len(frame) != 1)} in {ms:.1f} ms"
        if len(frame) > MAX_ROWS:  # run_sql fetches one row more than is shown, to tell when it cut
            status = f"More than {MAX_ROWS:,} rows: the first {MAX_ROWS:,} are shown. Narrow it with WHERE."
    except duckdb.Error as failure:
        frame, error, status = None, str(failure), "Failed"
    result = {"sql": sql, "explain": explain, "frame": frame, "error": error, "status": status}
    st.session_state.sql_result = result
    if not explain:
        others = [old for old in st.session_state.sql_history if old["sql"] != sql]
        st.session_state.sql_history = [{"sql": sql, "status": status}, *others][:20]


def er_diagram() -> str:
    """The star schema in gold, from the catalog, so it can't drift from the tables."""
    lines = [
        "erDiagram",
        '    dim_project ||--o{ fct_credit_event : "project_id"',
        '    dim_beneficial_owner |o--o{ fct_credit_event : "owner_key (retirements)"',
    ]
    for name in ["fct_credit_event", "dim_project", "dim_beneficial_owner"]:
        table = catalog[catalog["table_name"] == f"gold.{name}"].iloc[0]
        lines.append(f"    {name} {{")
        for column, kind in zip(table["columns"], table["types"], strict=True):
            lines.append(f"        {re.sub(r'\W+', '_', kind.lower())} {column}")
        lines.append("    }")
    return "\n".join(lines)


# arriving from another page's "Query … in SQL" link, or for the first time: load that query and run it
link = st.query_params.get("sql")
if "sql_history" not in st.session_state:
    st.session_state.sql_history = []
    load(link or EXAMPLES["Largest projects"])
elif link and link != st.session_state.get("sql_link"):
    load(link)
st.session_state.sql_link = link

st.title("SQL")
st.caption(
    "Every table, read-only. Bronze holds each record exactly as delivered, with its file and line; "
    "silver, the cleaned exports; gold, the model and the answers. A query can read nothing but these "
    f"tables, runs for at most {SECONDS} seconds, and shows at most {MAX_ROWS:,} rows."
)

navigator, workspace = st.columns([1.3, 3], gap="large")
with navigator:
    search = st.text_input(
        "Search tables and columns",
        type="search",
        placeholder="Table or column",
        key="sql_search",
        live=True,
        persist_state="session",
    )
    listing = catalog
    if search:
        words = search.strip().lower()
        found = catalog["columns"].map(lambda columns: ", ".join(c for c in columns if words in c.lower()))
        listing = listing.assign(found=found)
        listing = listing[listing["table_name"].str.lower().str.contains(words, regex=False) | (found != "")]
    picked = st.dataframe(
        listing,
        column_order=["table_name", "found"] if search else ["table_name", "rows"],
        column_config={
            "table_name": "Table",
            "rows": number("Rows"),
            "found": "Matching columns",
        },
        hide_index=True,
        height=38 + 35 * len(listing),  # every table at once, without a scrollbar
        on_select=lambda: st.session_state.update(sql_tab="Table"),
        selection_mode="single-row",
        key=f"sql_navigator {search}",  # a new search starts with nothing picked
        alt="Every table, gold first, with its rows and columns; pick one to see it",
    ).selection.rows
    table_name = listing.iloc[picked[0]]["table_name"] if picked else None

with workspace:
    query_tab, table_tab, diagram_tab, history_tab = st.tabs(
        ["Query", "Table", "Diagram", "History"], key="sql_tab", on_change="rerun"
    )
    if query_tab.open:
        with query_tab:
            st.pills(
                "Examples",
                list(EXAMPLES),
                key="sql_example",
                on_change=pick_example,
                label_visibility="collapsed",
            )
            with st.form("sql_form", border=False):
                # kept while another tab is open, and when you come back to this page
                st.text_area(
                    "SQL", key="sql_text", height=180, label_visibility="collapsed", persist_state="session"
                )
                with st.container(horizontal=True):
                    run = st.form_submit_button(
                        "Run", icon=":material/play_arrow:", help="Ctrl+Enter or Cmd+Enter"
                    )
                    explain = st.form_submit_button(
                        "Explain", icon=":material/account_tree:", help="DuckDB's plan"
                    )
            text, pending = st.session_state.sql_text, st.session_state.pop("sql_pending", False)
            last = st.session_state.get("sql_result")
            # Ctrl+Enter submits the form without pressing a button: a changed query means it was submitted
            if text.strip() and (run or explain or pending or (last and last["sql"] != text)):
                execute(text, explain=explain)
            result = st.session_state.get("sql_result")
            if result is None:
                st.caption("Type a query, then press Run.")
            elif result["error"]:
                st.error("The query failed", icon=":material/error:")
                st.code(result["error"], language=None)  # plain text: the message repeats what was typed
            elif result["explain"]:
                st.code("\n\n".join(result["frame"]["explain_value"]), language=None)
            else:
                st.dataframe(result["frame"].head(MAX_ROWS), hide_index=True, alt="The query's result")
                st.caption(result["status"])

    if table_tab.open:
        with table_tab:
            if table_name is None:
                st.caption(
                    "Pick a table in the navigator to see its columns, a profile of each, and its first rows."
                )
            else:
                row = catalog[catalog["table_name"] == table_name].iloc[0]
                st.subheader(table_name)
                st.caption(f"{row['rows']:,} rows and {len(row['columns'])} columns.")
                profile, _ = run_sql(lake, f"SUMMARIZE {table_name}")
                st.dataframe(
                    profile,
                    column_order=[
                        "column_name",
                        "column_type",
                        "null_percentage",
                        "approx_unique",
                        "min",
                        "max",
                    ],
                    column_config={
                        "column_name": "Column",
                        "column_type": "Type",
                        "null_percentage": st.column_config.NumberColumn("Empty %", format="%.1f"),
                        "approx_unique": number("Distinct, about"),
                        "min": "Smallest",
                        "max": "Largest",
                    },
                    hide_index=True,
                    alt=f"The columns of {table_name}, with their types and a profile of their values",
                )
                st.markdown("**First 100 rows**")
                first, _ = run_sql(lake, f"SELECT * FROM {table_name} LIMIT 100")
                st.dataframe(first, hide_index=True, alt=f"The first 100 rows of {table_name}")

    if diagram_tab.open:
        with diagram_tab:
            st.caption(
                "The star schema in gold: one fact table of every event, and its two dimensions. "
                "The marts are built from it."
            )
            st.mermaid_chart(
                er_diagram(), alt="The gold star schema: credit events, projects and beneficial owners"
            )

    if history_tab.open:
        with history_tab:
            if not st.session_state.sql_history:
                st.caption("The queries you run appear here, newest first.")
            for index, entry in enumerate(st.session_state.sql_history):
                st.code(entry["sql"], language="sql")
                with st.container(horizontal=True, vertical_alignment="center"):
                    st.caption(entry["status"])
                    st.button(
                        "Load",
                        key=f"sql_load_{index}",
                        icon=":material/edit:",
                        on_click=load,
                        args=(entry["sql"],),
                    )
