"""Credits issued, retired and cancelled per year, by the date of each event, or as running totals."""

import altair as alt
import pandas as pd
import streamlit as st
from common import CAPITALISED, COMPACT, GREY, INK, PALETTE, WHOLE, compact, number, snapshot, theme

lake, manifest, data = snapshot()
by_year = data["by_year"]

st.title("Over time")
st.caption("Credits issued, retired and cancelled per year, by the date of each event.")

dated = by_year.dropna(subset=["year"]).astype({"year": int})
wide = (
    dated.pivot_table(index="year", columns="event_type", values="credits", aggfunc="sum", fill_value=0)
    .reindex(columns=["issuance", "retirement", "cancellation"], fill_value=0)
    .reset_index()
    .rename(columns={"issuance": "issued", "retirement": "retired", "cancellation": "cancelled"})
)
undated = by_year[by_year["year"].isna()]  # events with no date: in every total, but on no year

if wide.empty:
    st.info("No event in this snapshot has a readable date: see Data quality.", icon=":material/info:")
    st.stop()

show = st.segmented_control("Show", ["Per year", "Running total"], default="Per year", key="over_time_show")
running = show == "Running total"
if running:
    lines = pd.DataFrame(
        {
            "year": wide["year"],
            "issued": wide["issued"].cumsum(),
            "used": (wide["retired"] + wide["cancelled"]).cumsum(),
        }
    )
    series = {"used": PALETTE[theme()][0], "issued": GREY}  # the story first, its context in grey
    alt_text = "Credits issued and used (retired or cancelled) so far, by year"
else:
    lines = wide[["year", "issued", "retired"]]
    series = {"retired": PALETTE[theme()][0], "issued": GREY}
    alt_text = "Credits retired per year, against credits issued per year in grey"

long = lines.melt(id_vars="year", var_name="series", value_name="credits")
long["label"] = long["series"].str.capitalize() + " " + long["credits"].map(compact)
nearest = alt.selection_point(nearest=True, on="pointerover", fields=["year"], empty=False)
base = alt.Chart(long).encode(
    x=alt.X("year:O", title=None, axis=alt.Axis(labelAngle=0, labelOverlap=True)),
    y=alt.Y("credits:Q", title=None, axis=alt.Axis(format="~s", labelExpr=COMPACT, tickCount=6)),
    color=alt.Color(
        "series:N",
        scale=alt.Scale(domain=list(series), range=list(series.values())),
        legend=alt.Legend(title=None, orient="top", labelExpr=CAPITALISED),
    ),
)
# the end labels wear ink: the line beside each one carries its colour
chart = (
    base.mark_line(strokeWidth=2)
    + base.mark_point(filled=True, size=64).encode(opacity=alt.condition(nearest, alt.value(1), alt.value(0)))
    + base.transform_filter(alt.datum.year == int(lines["year"].max()))
    .mark_text(align="left", dx=8, fontSize=12)
    .encode(text="label:N", color=alt.value(INK[theme()]))
    + alt.Chart(lines)
    .mark_rule(color=GREY)
    .encode(
        x="year:O",
        opacity=alt.condition(nearest, alt.value(0.5), alt.value(0)),
        tooltip=[alt.Tooltip("year:O")] + [alt.Tooltip(f"{name}:Q", format=",") for name in series],
    )
    .add_params(nearest)
)
st.altair_chart(chart.properties(height=360), alt=alt_text)
if running:  # undated events never join a line, so then the gap and what's available differ by them
    apart = ", apart from the undated events below, which have no year" if len(undated) else ""
    st.caption(f"The gap between the two lines is the credits still available{apart}.")
if len(undated):
    events = zip(undated["event_type"], undated["events"], strict=True)
    kinds = ", ".join(f"{n:,} {kind}{'s' * (n != 1)}" for kind, n in events)
    verb = "has" if undated["events"].sum() == 1 else "have"
    st.caption(
        f"{kinds} ({int(undated['credits'].sum()):,} credits) {verb} no date, so they aren't on this chart. "
        "They count in every total."
    )

st.dataframe(
    wide,
    column_config={
        "year": st.column_config.NumberColumn("Year", format=WHOLE),
        "issued": number("Issued"),
        "retired": number("Retired"),
        "cancelled": number("Cancelled"),
    },
    hide_index=True,
    alt="Credits issued, retired and cancelled in each year",
)
