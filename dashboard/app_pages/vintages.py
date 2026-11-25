"""Question 2: credit activity by vintage, the year or years in which the emission reductions happened."""

import streamlit as st
from common import INK, PARTS, USED, WHOLE, number, parts_chart, share_line, snapshot, theme, used

lake, manifest, data = snapshot()
activity = data["vintages"]

st.title("Vintages")
st.caption(
    "Question 2: credit activity by vintage, the year or years in which the emission reductions happened."
)

show = st.segmented_control("Show", ["Credits", "Share of issued"], default="Credits", key="vintages_show")
by_year = activity.groupby("vintage_start", as_index=False)[["issued", *PARTS]].sum()
share = show == "Share of issued"
st.altair_chart(
    parts_chart(by_year, "vintage_start", horizontal=False, share=share),
    alt="Credits by first vintage year, split into retired, cancelled and available"
    + (", as shares of what each vintage issued" if share else ""),
)

issued = activity["issued"].sum()
spans = activity.loc[activity["vintage_start"] < activity["vintage_end"], "issued"].sum()
share_line(
    spans / issued if issued else 0,
    "of issued credits have a vintage that spans years, such as 2007 - 2008. The chart counts them in "
    "their first year.",
    INK[theme()],
    "The share of issued credits whose vintage spans more than one year",
)

st.dataframe(
    activity.assign(used=used(activity)),
    column_order=[
        "vintage",
        "vintage_start",
        "vintage_end",
        "projects",
        "issued",
        "retired",
        "cancelled",
        "available",
        "used",
    ],
    column_config={
        "vintage": "Vintage",
        "vintage_start": st.column_config.NumberColumn("First year", format=WHOLE),
        "vintage_end": st.column_config.NumberColumn("Last year", format=WHOLE),
        "projects": number("Projects"),
        "issued": number("Issued"),
        "retired": number("Retired"),
        "cancelled": number("Cancelled"),
        "available": number("Available"),
        "used": USED,
    },
    hide_index=True,
    alt="Every vintage as Verra writes it, with its credits issued, retired, cancelled and available",
)
st.page_link(
    "app_pages/sql.py",
    label="Query the vintages in SQL",
    icon=":material/database:",
    query_params={"sql": "SELECT * FROM gold.mart_vintage_activity ORDER BY vintage_start, vintage_end"},
)
