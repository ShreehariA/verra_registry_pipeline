"""Question 1: for each project, how much was issued, retired and cancelled, and how much is left."""

import streamlit as st
from common import (
    PALETTE,
    USED,
    WHOLE,
    ledger_bar,
    number,
    parts_chart,
    plain,
    ranked_bars,
    snapshot,
    theme,
    used,
)

lake, manifest, data = snapshot()
balance = data["balance"]
issued = balance["issued"].sum()

st.title("Projects")
st.caption(
    "Question 1: for each project, how much was issued, retired and cancelled, and how much is still "
    "available."
)

largest = balance.nlargest(15, "issued")
if len(largest) and issued:
    st.subheader("The 15 largest projects, by credits issued")
    top = largest.iloc[0]
    share = top.issued / issued
    st.altair_chart(
        parts_chart(largest, "project_name", horizontal=True),
        alt=f"The 15 largest projects by credits issued. The largest has {share:.0%} of them all.",
    )
    st.caption(f"{plain(top.project_name)} alone holds {share:.0%} of every credit issued.")

st.subheader(f"All {len(balance):,} projects")
search = st.text_input(
    "Find a project", type="search", placeholder="Name, ID or country", key="projects_search", live=True
)
shown = balance
if search:
    words = search.strip().lower()
    shown = balance[
        balance["project_name"].str.lower().str.contains(words, regex=False)
        | balance["country"].fillna("").str.lower().str.contains(words, regex=False)
        | (balance["project_id"].astype(str) == words)
    ]
shown = shown.sort_values("issued", ascending=False)
shown = shown.assign(used=used(shown))
event = st.dataframe(
    shown,
    column_order=[
        "project_name",
        "project_id",
        "country",
        "issued",
        "retired",
        "cancelled",
        "available",
        "used",
    ],
    column_config={
        "project_name": st.column_config.TextColumn("Project", pinned=True),
        "project_id": st.column_config.NumberColumn("ID", format=WHOLE),
        "country": "Country",
        "issued": number("Issued"),
        "retired": number("Retired"),
        "cancelled": number("Cancelled"),
        "available": number("Available"),
        "used": USED,
    },
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    key=f"projects_table {search}",  # a new search starts with nothing picked
    alt="Every project with its credits issued, retired, cancelled and available, and the share used",
)

if not event.selection.rows:
    st.caption("Pick a row to see that project: its vintages, and who retired its credits.")
else:
    project = shown.iloc[event.selection.rows[0]]
    st.subheader(plain(project.project_name))
    st.caption(f"Project {project.project_id}, {plain(project.country)}. {plain(project.sectoral_scope)}.")
    st.altair_chart(ledger_bar(project), alt="What happened to this project's issued credits")
    by_vintage, by_owner = st.columns(2, gap="large")
    with by_vintage:
        st.markdown("**By vintage**")
        vintages = data["project_vintages"]
        vintages = vintages[vintages["project_id"] == project.project_id]
        vintages = vintages.assign(available=vintages["issued"] - vintages["retired"] - vintages["cancelled"])
        st.altair_chart(
            parts_chart(vintages, "vintage_start", horizontal=False),
            alt="This project's credits by vintage: issued, retired, cancelled and available",
        )
    with by_owner:
        st.markdown("**Who retired its credits**")
        owners = data["retirers"]
        owners = owners[owners["project_id"] == project.project_id]
        named = owners.dropna(subset=["owner_rank"]).nlargest(10, "credits")
        unnamed = owners.loc[owners["owner_key"] == "unspecified", "credits"].sum()
        if len(named):
            st.altair_chart(
                ranked_bars(named, "owner_name", "credits", PALETTE[theme()][0]),
                alt="The owners who retired the most of this project's credits",
            )
        else:
            st.caption("No retirement of this project names an owner.")
        if unnamed:
            st.caption(f"{unnamed:,} more retired credits of this project name no owner.")

st.page_link(
    "app_pages/sql.py",
    label="Query the projects in SQL",
    icon=":material/database:",
    query_params={"sql": "SELECT * FROM gold.mart_project_balance ORDER BY issued DESC"},
)
