"""Question 3: who retires the most credits, and what they retire."""

import streamlit as st
from common import PALETTE, number, ranked_bars, share_line, short, snapshot, theme

lake, manifest, data = snapshot()
retired, spellings = data["retirers"], data["owners"]
blue = PALETTE[theme()][0]

st.title("Retirers")
st.caption("Question 3: who retires the most credits, and what they retire.")

total = retired["credits"].sum()
unnamed = retired.loc[retired["owner_key"] == "unspecified", "credits"].sum()
share_line(
    unnamed / total if total else 0,
    "of retired credits name no owner: the field is blank, or a placeholder such as _ or N/A. They count in "
    "every total, but aren't ranked.",
    blue,
    "The share of retired credits that name no owner",
)

owners = retired.dropna(subset=["owner_rank"]).drop_duplicates("owner_key").sort_values("owner_rank")
if owners.empty:
    st.info("No retirement in this snapshot names an owner.", icon=":material/info:")
    st.stop()

count = st.segmented_control(
    "Owners shown", [10, 25, 50], default=10, key="retirers_count", format_func=lambda n: f"Top {n}"
)
st.altair_chart(
    ranked_bars(owners.head(count or 10), "owner_name", "owner_credits", blue),
    alt="The named owners who retired the most credits, largest first",
)
st.caption(
    "Each owner is all its spellings counted together: Interface, Inc. and INTERFACE INC are one owner."
)

names = dict(zip(owners["owner_key"], owners["owner_name"], strict=True))
key = st.selectbox(
    "See what an owner retires", list(names), format_func=lambda k: short(names[k]), key="retirers_pick"
)
theirs = retired[retired["owner_key"] == key].sort_values("credits", ascending=False)
st.altair_chart(
    ranked_bars(theirs.head(10), "project_name", "credits", blue),
    alt="The projects this owner retired the most credits from",
)
st.dataframe(
    theirs,
    column_order=[
        "project_name",
        "country",
        "sectoral_scope",
        "vintages",
        "credits",
        "retirements",
        "first_retired",
        "last_retired",
    ],
    column_config={
        "project_name": "Project",
        "country": "Country",
        "sectoral_scope": "Sectoral scope",
        "vintages": "Vintages",
        "credits": number("Credits"),
        "retirements": number("Retirements"),
        "first_retired": st.column_config.DateColumn("First retired"),
        "last_retired": st.column_config.DateColumn("Last retired"),
    },
    hide_index=True,
    alt="Every project this owner retired credits from",
)
st.markdown("**Written in the files as**")
st.text(spellings.loc[spellings["owner_key"] == key, "spellings"].iloc[0])  # plain text: typed in by anyone

st.page_link(
    "app_pages/sql.py",
    label="Query the retirers in SQL",
    icon=":material/database:",
    query_params={
        "sql": "SELECT * FROM gold.mart_top_retirers WHERE owner_rank <= 10 ORDER BY owner_rank, credits DESC"
    },
)
