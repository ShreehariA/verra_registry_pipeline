"""What every page of the dashboard shares: the lake's data, the colours, number formats and the chart forms.

The chart forms follow the dataviz skill: the ledger bar for one whole split into the three fates of a
credit, a meter for one share, stacked bars for several wholes, and ranked bars in one hue.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from verra_pipeline.config import load
from verra_pipeline.lake import connect, lock_down, newest_manifest

# what happened to the issued credits: same order and colour everywhere
PARTS = ["retired", "cancelled", "available"]
# Slots 1-3 of the dataviz reference palette, validated together on each theme's surface (validate_palette.py)
PALETTE = {"light": ["#2a78d6", "#eb6834", "#1baf7a"], "dark": ["#3987e5", "#d95926", "#199e70"]}
SURFACE = {"light": "#ffffff", "dark": "#0e1117"}  # the 2px gap between touching marks
INK = {"light": "#22313a", "dark": "#e6ecee"}
GREY = "#898781"  # context: what the highlighted series is read against
MAX_ROWS = 1_000  # the SQL page shows at most this many rows
SECONDS = 10  # and stops a query after this long
# the share of issued credits retired or cancelled, as a percentage (see used())
USED = st.column_config.ProgressColumn("Used", min_value=0, max_value=100, format="%.0f%%")
WHOLE = "%d"  # years, IDs, line numbers: Streamlit's "plain" format shows 2011 as 2010.9999999999998
CAPITALISED = "upper(slice(datum.label, 0, 1)) + slice(datum.label, 1)"  # legend labels in sentence case
COMPACT = "datum.value == 0 ? '0' : format(datum.value, '~s')"  # axis labels: 0, 5M, 10M (never "0M")

QUERIES = {
    "balance": "SELECT * FROM gold.mart_project_balance",
    "vintages": "SELECT * FROM gold.mart_vintage_activity",
    "retirers": "SELECT * FROM gold.mart_top_retirers",
    "owners": "SELECT owner_key, spellings FROM gold.dim_beneficial_owner",
    "by_year": "SELECT year(event_date) AS year, event_type, count(*) AS events, "
    "sum(quantity)::BIGINT AS credits FROM gold.fct_credit_event GROUP BY ALL ORDER BY ALL",
    "project_vintages": "SELECT project_id, vintage_start, "
    "coalesce(sum(quantity) FILTER (event_type = 'issuance'), 0)::BIGINT AS issued, "
    "coalesce(sum(quantity) FILTER (event_type = 'retirement'), 0)::BIGINT AS retired, "
    "coalesce(sum(quantity) FILTER (event_type = 'cancellation'), 0)::BIGINT AS cancelled "
    "FROM gold.fct_credit_event GROUP BY ALL ORDER BY ALL",
    "checks": "SELECT * FROM gold.quality_results",
    "rejected": "SELECT _source_file AS file, _source_line AS line, reason, raw_text "
    "FROM bronze.rejected_records",
    # the SQL page's navigator: the answers first, the raw rows last
    "catalog": "SELECT schema || '.' || name AS table_name, schema AS layer, column_names AS columns, "
    "column_types AS types FROM (SHOW ALL TABLES) "
    "ORDER BY list_position(['gold', 'silver', 'bronze'], schema), name",
}


@st.cache_data(show_spinner=False, max_entries=1)
def read_lake(lake: str, version: str) -> dict[str, pd.DataFrame]:
    """Every table the pages need. `version` names the manifest behind them, so a new build reloads."""
    with connect(Path(lake)) as con:
        data = {name: con.sql(sql).df() for name, sql in QUERIES.items()}
        catalog = data["catalog"]
        catalog["rows"] = [
            con.execute(f"SELECT count(*) FROM {t}").fetchall()[0][0] for t in catalog["table_name"]
        ]
    return data


def lake_path() -> Path:
    return Path(os.environ.get("VERRA_LAKE") or load(Path("pipeline.toml")).lake)


def snapshot() -> tuple[Path, dict[str, Any], dict[str, pd.DataFrame]]:
    """The lake, its newest manifest and every table the pages read. app.py has checked a snapshot exists."""
    lake = lake_path()
    path = newest_manifest(lake)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    return lake, manifest, read_lake(str(lake), f"{path}@{path.stat().st_mtime_ns}")


def theme() -> str:
    return "dark" if getattr(st.context.theme, "type", None) == "dark" else "light"


def colours() -> alt.Scale:
    return alt.Scale(domain=PARTS, range=PALETTE[theme()])


def number(label: str) -> Any:
    """A table column of whole numbers with thousands separators: tables keep every digit."""
    return st.column_config.NumberColumn(label, format="localized")


def used(frame: pd.DataFrame) -> pd.Series:
    """The share of issued credits retired or cancelled, as a percentage; empty when nothing was issued."""
    return 100 * (frame["retired"] + frame["cancelled"]) / frame["issued"].where(frame["issued"] > 0)


def compact(n: float) -> str:
    """198,511,826 as 198.5M: for figures read at a glance. Tables keep every digit."""
    for size, unit in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= size:
            return f"{n / size:.1f}{unit}"
    return f"{n:,.0f}"


def plain(text: Any) -> str:
    """Registry text for an element that renders Markdown: owner and project names are typed in by anyone, and
    one like `[Claim credits](https://…)` must not become a link on a public page."""
    return re.sub(r"([\\`*_{}\[\]()<>#+\-.!|~:$])", r"\\\1", str(text))


def short(name: str) -> str:
    """A 42-character wallet address as 0x5298…26e2, so it doesn't crowd out the names around it."""
    return f"{name[:6]}…{name[-4:]}" if re.fullmatch(r"0x[0-9a-fA-F]{40}", name) else name


def ledger_bar(credits: dict[str, Any]) -> alt.LayerChart:
    """One whole split into the three fates (dataviz's tall segmented bar): 28px, 2px gaps between blocks,
    each share printed inside its block when it fits, otherwise beside its name in the legend."""
    mode = theme()
    # a project used more than it was issued (a warning check) has a negative balance: it draws as no block
    frame = pd.DataFrame({"part": PARTS, "credits": [max(credits[part], 0) for part in PARTS]})
    frame["share"] = frame["credits"] / max(frame["credits"].sum(), 1)
    frame["end"] = frame["share"].cumsum()
    frame["start"] = frame["end"] - frame["share"]
    fits = frame["share"] >= 0.07
    frame["inside"] = frame["share"].map("{:.1%}".format).where(fits, "")
    frame["name"] = frame["part"].str.capitalize() + frame["share"].map(" {:.1%}".format).where(~fits, "")
    names = alt.Scale(domain=frame["name"].tolist(), range=PALETTE[mode])
    tooltip = [
        alt.Tooltip("part:N", title="credits"),
        alt.Tooltip("credits:Q", title="amount", format=","),
        alt.Tooltip("share:Q", format=".1%"),
    ]
    blocks = (
        alt.Chart(frame)
        .mark_bar(height=28, cornerRadius=4, stroke=SURFACE[mode], strokeWidth=2)
        .encode(
            x=alt.X("start:Q", scale=alt.Scale(domain=[0, 1]), axis=None),
            x2="end:Q",
            color=alt.Color(
                "name:N",
                scale=names,
                sort=frame["name"].tolist(),
                legend=alt.Legend(title=None, orient="bottom", symbolType="square", labelFontSize=13),
            ),
            tooltip=tooltip,
        )
    )
    labels = (
        alt.Chart(frame)
        .mark_text(align="left", dx=10, color="#ffffff", fontWeight=600, fontSize=13)
        .encode(x="start:Q", text="inside:N", tooltip=tooltip)
    )
    return (blocks + labels).properties(height=64)  # the 28px bar, and room for its legend underneath


def meter(share: float, colour: str) -> alt.LayerChart:
    """One share against its whole (dataviz's meter): the fill, on a lighter track of the same hue."""
    frame = pd.DataFrame({"start": [0.0, 0.0], "end": [1.0, share], "layer": ["track", "fill"]})
    return (
        alt.Chart(frame)
        .mark_bar(height=8, cornerRadius=4)
        .encode(
            x=alt.X("start:Q", scale=alt.Scale(domain=[0, 1]), axis=None),
            x2="end:Q",
            color=alt.Color(
                "layer:N", scale=alt.Scale(domain=["track", "fill"], range=[colour, colour]), legend=None
            ),
            opacity=alt.Opacity(
                "layer:N", scale=alt.Scale(domain=["track", "fill"], range=[0.18, 1]), legend=None
            ),
        )
        .properties(height=10)
    )


def share_line(share: float, sentence: str, colour: str, alt_text: str) -> None:
    """A meter with its figure and what it means, in place of a paragraph."""
    st.markdown(f"**{share:.1%}** {sentence}")
    st.altair_chart(meter(share, colour), alt=alt_text)


def parts_chart(frame: pd.DataFrame, by: str, horizontal: bool, share: bool = False) -> alt.Chart:
    """Stacked bars of what happened to the issued credits of several wholes: retired, cancelled, available.
    With `share`, every bar is the same length and shows the split instead of the size."""
    mode = theme()
    long = frame.melt(id_vars=[by, "issued"], value_vars=PARTS, var_name="part", value_name="credits")
    long["order"] = long["part"].map(PARTS.index)
    stack: Any = "normalize" if share else True
    axis = (
        alt.Axis(format="%", tickCount=5, title=None)
        if share
        else alt.Axis(format="~s", labelExpr=COMPACT, tickCount=5, title=None)
    )
    if horizontal:  # names down the side, credits along
        x = alt.X("credits:Q", stack=stack, axis=axis)
        y = alt.Y(f"{by}:N", sort=None, title=None, axis=alt.Axis(labelLimit=320))
    else:  # years along, credits up
        x = alt.X(f"{by}:O", title=None, axis=alt.Axis(labelAngle=0, labelOverlap=True))
        y = alt.Y("credits:Q", stack=stack, axis=axis)
    chart = (
        alt.Chart(long)
        .mark_bar(size=16 if horizontal else 18, stroke=SURFACE[mode], strokeWidth=2)
        .encode(
            x,
            y,
            color=alt.Color(
                "part:N",
                scale=colours(),
                sort=PARTS,
                legend=alt.Legend(title=None, orient="top", symbolType="square", labelExpr=CAPITALISED),
            ),
            order=alt.Order("order:Q"),
            tooltip=[
                alt.Tooltip(f"{by}:N", title=by.replace("_", " ")),
                alt.Tooltip("part:N"),
                alt.Tooltip("credits:Q", format=","),
                alt.Tooltip("issued:Q", format=","),
            ],
        )
    )
    return chart.properties(height=alt.Step(26) if horizontal else 340)


def ranked_bars(frame: pd.DataFrame, name: str, value: str, colour: str) -> alt.LayerChart:
    """Largest first, in one hue (a ranking compares names, not categories), with the value at each tip."""
    frame = frame.assign(label=frame[name].map(short))
    bars = (
        alt.Chart(frame)
        .mark_bar(size=16, cornerRadiusEnd=4, color=colour)
        .encode(
            x=alt.X(f"{value}:Q", title=None, axis=alt.Axis(format="~s", labelExpr=COMPACT, tickCount=5)),
            y=alt.Y("label:N", sort=None, title=None, axis=alt.Axis(labelLimit=320)),
            tooltip=[
                alt.Tooltip(f"{name}:N", title="name"),
                alt.Tooltip(f"{value}:Q", title="credits", format=","),
            ],
        )
    )
    tips = bars.mark_text(align="left", dx=6, color=INK[theme()], fontSize=12).encode(
        text=alt.Text(f"{value}:Q", format=",")
    )
    return (bars + tips).properties(height=alt.Step(26))


def run_sql(lake: Path, sql: str) -> tuple[pd.DataFrame, float]:
    """A viewer's SQL, on its own locked-down copy of the tables, and how long the query took in milliseconds.
    MAX_ROWS + 1 rows back means the result was cut."""
    with connect(lake, copy=True) as con:
        lock_down(con, SECONDS)
        started = time.perf_counter()
        result = con.sql(sql)  # None when the last statement returns no rows
        frame = pd.DataFrame() if result is None else result.limit(MAX_ROWS + 1).df()
        return frame, (time.perf_counter() - started) * 1000
