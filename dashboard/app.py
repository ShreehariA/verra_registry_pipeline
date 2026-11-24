"""The dashboard: the brief's three questions, and how far the data can be trusted.

Run it with `make dashboard`. It shows the newest finished snapshot in the lake of pipeline.toml, or in
$VERRA_LAKE when that is set (the cloud demo mounts the bucket there). Each view has its own URL, ?view=...
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from verra_pipeline import PipelineError
from verra_pipeline.config import load
from verra_pipeline.lake import connect, newest_manifest

VIEWS = ["Projects", "Vintages", "Retirers", "Over time", "Data quality"]  # each one's URL is ?view=<name>
PARTS = [
    "retired",
    "cancelled",
    "available",
]  # what happened to the issued credits: same order and colour everywhere
# The first three categorical slots of the dataviz reference palette, validated for each theme's surface.
PALETTE = {"light": ["#2a78d6", "#eb6834", "#1baf7a"], "dark": ["#3987e5", "#d95926", "#199e70"]}
SURFACE = {
    "light": "#ffffff",
    "dark": "#0e1117",
}  # Streamlit's backgrounds: the 2px gap between touching marks
CONTEXT_GREY = "#898781"
QUERIES = {
    "balance": "SELECT * FROM gold.mart_project_balance",
    "vintages": "SELECT * FROM gold.mart_vintage_activity",
    "retirers": "SELECT * FROM gold.mart_top_retirers",
    "owners": "SELECT owner_key, spellings FROM gold.dim_beneficial_owner",
    "by_year": "SELECT year(event_date) AS year, event_type, count(*) AS events, "
    "sum(quantity)::BIGINT AS credits FROM gold.fct_credit_event GROUP BY ALL ORDER BY ALL",
    "checks": "SELECT * FROM gold.quality_results",
    "rejected": "SELECT _source_file AS file, _source_line AS line, reason, raw_text "
    "FROM bronze.rejected_records",
}
NUMBER = st.column_config.NumberColumn(format="localized")


@st.cache_data(show_spinner=False, max_entries=1)
def read_lake(lake: str, version: str) -> dict[str, pd.DataFrame]:
    """Every table the views need. `version` names the manifest behind them, so a new build reloads."""
    with connect(Path(lake)) as con:
        return {name: con.sql(sql).df() for name, sql in QUERIES.items()}


def main() -> None:
    st.set_page_config(page_title="Verra registry", layout="wide")
    try:
        lake = Path(os.environ.get("VERRA_LAKE") or load(Path("pipeline.toml")).lake)
        manifest_path = newest_manifest(lake)
    except PipelineError as error:
        st.error(str(error))
        st.stop()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    data = read_lake(str(lake), f"{manifest_path}@{manifest_path.stat().st_mtime_ns}")
    theme = "dark" if getattr(st.context.theme, "type", None) == "dark" else "light"

    credits = manifest["credits"]
    st.title("Verra registry")
    st.caption(
        f"Snapshot {manifest['snapshot_date']} · built by `verra build` from Verra's three daily exports"
    )
    tiles = st.columns(5)
    tiles[0].metric("Issued", f"{credits['issued']:,}")
    tiles[1].metric("Retired", f"{credits['retired']:,}")
    tiles[2].metric("Cancelled", f"{credits['cancelled']:,}")
    share = f"{credits['available'] / credits['issued']:.1%} of issued" if credits["issued"] else None
    tiles[3].metric("Available", f"{credits['available']:,}", share, delta_color="off", delta_arrow="off")
    tiles[4].metric("Projects", f"{len(data['balance']):,}")

    view = st.radio("View", VIEWS, horizontal=True, key="view", bind="query-params")
    colours = alt.Scale(domain=PARTS, range=PALETTE[theme])
    if view == "Projects":
        projects(data["balance"], colours, theme)
    elif view == "Vintages":
        vintages(data["vintages"], colours, theme)
    elif view == "Retirers":
        retirers(data["retirers"], data["owners"], PALETTE[theme][0])
    elif view == "Over time":
        over_time(data["by_year"], PALETTE[theme][0])
    else:
        quality(data["checks"], data["rejected"], manifest)


def projects(balance: pd.DataFrame, colours: alt.Scale, theme: str) -> None:
    st.subheader("Question 1: for each project, how much was issued, retired and cancelled, and what's left?")
    top = balance.nlargest(15, "issued")
    st.altair_chart(parts_chart(top, "project_name", colours, theme, horizontal=True), width="stretch")
    st.caption(
        "The 15 largest projects by credits issued. Each bar is all that was issued, split by what happened."
    )
    search = st.text_input("Find a project", placeholder="name, ID or country").strip().lower()
    labels = (
        balance["project_id"].astype(str)
        + " "
        + balance["project_name"]
        + " "
        + balance["country"].fillna("")
    )
    shown = balance[labels.str.lower().str.contains(search, regex=False, na=False)] if search else balance
    st.dataframe(
        shown.assign(available_share=shown["available"] / shown["issued"].where(shown["issued"] > 0)),
        hide_index=True,
        column_config={
            **dict.fromkeys(["issued", *PARTS], NUMBER),
            "available_share": st.column_config.NumberColumn("available %", format="percent"),
        },
    )
    totals = " · ".join(f"{name} {shown[name].sum():,}" for name in ["issued", *PARTS])
    st.caption(f"{len(shown):,} projects · {totals}")


def vintages(activity: pd.DataFrame, colours: alt.Scale, theme: str) -> None:
    st.subheader("Question 2: credit activity by vintage, the year the emission reductions happened")
    by_year = activity.groupby("vintage_start", as_index=False)[["issued", *PARTS]].sum()
    st.altair_chart(parts_chart(by_year, "vintage_start", colours, theme, horizontal=False), width="stretch")
    ranges = activity.loc[activity["vintage_start"] != activity["vintage_end"], "issued"].sum()
    st.caption(
        f"A vintage that spans years, such as 2007 - 2008, is counted in its first year: {ranges:,} "
        f"credits, {ranges / max(activity['issued'].sum(), 1):.1%} of everything issued. The files don't "
        "say how such a range splits across its years. The table keeps every vintage as Verra writes it."
    )
    st.dataframe(activity, hide_index=True, column_config=dict.fromkeys(["issued", *PARTS], NUMBER))


def retirers(retired: pd.DataFrame, owners: pd.DataFrame, colour: str) -> None:
    st.subheader("Question 3: who are the largest retirers, and what do they retire?")
    per_owner = retired.drop_duplicates("owner_key")
    unnamed = per_owner.loc[per_owner["owner_key"] == "unspecified", "owner_credits"].sum()
    st.caption(
        f"{unnamed:,} retired credits ({unnamed / max(per_owner['owner_credits'].sum(), 1):.1%}) name no "
        "owner: blank, or a placeholder such as `_` or `N/A`. They are not ranked. Spellings of one owner "
        "(`Interface, Inc.`, `INTERFACE INC`, mis-encoded names) are counted as one."
    )
    count = st.slider("Owners shown", 5, 30, 15)
    top = per_owner.dropna(subset=["owner_rank"]).nsmallest(count, "owner_rank")
    if top.empty:
        st.info("No retirement in this snapshot names an owner.")
        return
    bars = alt.Chart(top).encode(
        x=alt.X("owner_credits:Q", title="credits retired", axis=alt.Axis(format="~s", tickCount=6)),
        y=alt.Y("owner_name:N", sort=None, title=None, axis=alt.Axis(labelLimit=320)),
        tooltip=[
            alt.Tooltip("owner_rank:Q", title="rank"),
            alt.Tooltip("owner_name:N", title="owner"),
            alt.Tooltip("owner_credits:Q", title="credits", format=","),
        ],
    )
    chart = bars.mark_bar(size=14, color=colour, cornerRadiusEnd=4) + bars.mark_text(
        align="left", dx=4, color=CONTEXT_GREY
    ).encode(text=alt.Text("owner_credits:Q", format=","))
    st.altair_chart(chart.properties(height=alt.Step(28)), width="stretch")

    names = dict(
        zip(
            top["owner_key"],
            top["owner_rank"].astype(int).astype(str) + ". " + top["owner_name"],
            strict=True,
        )
    )
    key = st.selectbox("What does this owner retire?", list(names), format_func=names.__getitem__)
    rows = retired[retired["owner_key"] == key]
    st.dataframe(
        rows[["project_id", "project_name", "sectoral_scope", "country", "vintages", "credits", "retirements",
              "first_retired", "last_retired"]],
        hide_index=True,
        column_config={"credits": NUMBER, "retirements": NUMBER},
    )  # fmt: skip
    # plain text: owner names are free text typed into the registry, never Markdown for a public page
    st.text("Spelled in the files as: " + owners.loc[owners["owner_key"] == key, "spellings"].iloc[0])


def over_time(by_year: pd.DataFrame, colour: str) -> None:
    st.subheader("Retirements per year, against issuance")
    named = {"issuance": "issued", "retirement": "retired", "cancellation": "cancelled"}
    dated = (
        by_year.dropna(subset=["year"])
        .astype({"year": int})
        .assign(kind=lambda f: f["event_type"].map(named))
    )
    if dated.empty:
        st.info("No event in this snapshot has a readable date: see Data quality.")
        return
    wide = dated.pivot_table(index="year", columns="kind", values="credits", aggfunc="sum", fill_value=0)
    wide = wide.reindex(columns=["issued", "retired", "cancelled"], fill_value=0).reset_index()
    lines = alt.Chart(dated[dated["kind"] != "cancelled"]).encode(
        x=alt.X("year:O", title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("credits:Q", title="credits", axis=alt.Axis(format="~s", tickCount=6)),
        color=alt.Color(
            "kind:N",
            scale=alt.Scale(domain=["retired", "issued"], range=[colour, CONTEXT_GREY]),
            legend=alt.Legend(title=None, orient="top"),
        ),
    )
    end_labels = lines.transform_filter(alt.datum.year == int(dated["year"].max())).mark_text(
        align="left", dx=8
    )
    pointer = alt.selection_point(nearest=True, on="pointerover", fields=["year"], empty=False)
    crosshair = (
        alt.Chart(wide)
        .mark_rule(color=CONTEXT_GREY)
        .encode(
            x="year:O",
            opacity=alt.condition(pointer, alt.value(0.6), alt.value(0)),
            tooltip=["year:O", *(alt.Tooltip(f"{kind}:Q", format=",") for kind in wide.columns[1:])],
        )
        .add_params(pointer)
    )
    chart = (
        lines.mark_line(strokeWidth=2, strokeCap="round")
        + lines.mark_point(filled=True, size=64)
        + end_labels.encode(
            text="kind:N", color=alt.value(CONTEXT_GREY)
        )  # text never wears the series colour
        + crosshair
    )
    st.altair_chart(chart.properties(height=360), width="stretch")
    undated = by_year[by_year["year"].isna() & (by_year["event_type"] == "retirement")]
    if not undated.empty:
        st.caption(
            f"{int(undated['events'].sum()):,} retirements ({int(undated['credits'].sum()):,} credits) have "
            "no date in the file, so they are not on this chart. They count in every total."
        )
    st.dataframe(wide, hide_index=True, column_config=dict.fromkeys(["issued", *PARTS[:2]], NUMBER))


def quality(checks: pd.DataFrame, rejected: pd.DataFrame, manifest: dict[str, Any]) -> None:
    st.subheader("How far the numbers can be trusted")
    errors = checks[checks["severity"] == "error"]
    st.success(
        f"Quality gate passed: all {len(errors)} error checks are clean. Totals reconcile from the raw "
        "files through bronze, silver and gold to every chart here.",
        icon="✅",
    )
    for check in checks[(checks["severity"] == "warning") & ~checks["passed"]].itertuples():
        credits = f", {check.failing_credits:,} credits" if check.failing_credits else ""
        st.warning(f"{check.check_name}: {check.failing_rows:,} row(s){credits}", icon="⚠️")
    status = checks["passed"].map({True: "✅ passed", False: "⚠️ see above"})
    st.dataframe(
        checks.assign(status=status)[["status", "severity", "check_name", "failing_rows", "failing_credits"]],
        hide_index=True,
        column_config={"failing_rows": NUMBER, "failing_credits": NUMBER},
    )
    st.markdown("**Records that could not be read**, kept with their exact text")
    st.dataframe(rejected, hide_index=True)
    st.markdown("**What the files looked like**")
    for entry in manifest["files"]:
        notes = "; ".join(entry["findings"]) or "nothing unusual"
        st.markdown(
            f"- `{entry['file']}` ({entry['rows_loaded']:,} rows, sha256 `{entry['sha256'][:12]}…`): {notes}"
        )


def parts_chart(frame: pd.DataFrame, by: str, colours: alt.Scale, theme: str, horizontal: bool) -> alt.Chart:
    """Stacked bars of what happened to the issued credits: retired, cancelled and still available."""
    long = frame.melt(id_vars=[by, "issued"], value_vars=PARTS, var_name="part", value_name="credits")
    long["order"] = long["part"].map(PARTS.index)
    value = alt.X("credits:Q", title="credits", axis=alt.Axis(format="~s", tickCount=6), stack=True)
    category = alt.Y(f"{by}:N", sort=None, title=None, axis=alt.Axis(labelLimit=320))
    if not horizontal:
        value = alt.Y("credits:Q", title="credits", axis=alt.Axis(format="~s", tickCount=6), stack=True)
        category = alt.X(f"{by}:O", title=None, axis=alt.Axis(labelAngle=0))
    chart = (
        alt.Chart(long)
        .mark_bar(size=14 if horizontal else 18, stroke=SURFACE[theme], strokeWidth=2)
        .encode(
            value,
            category,
            color=alt.Color("part:N", scale=colours, sort=PARTS, legend=alt.Legend(title=None, orient="top")),
            order=alt.Order("order:Q"),
            tooltip=[
                alt.Tooltip(f"{by}:N", title=by.replace("_", " ")),
                alt.Tooltip("part:N"),
                alt.Tooltip("credits:Q", format=","),
                alt.Tooltip("issued:Q", format=","),
            ],
        )
    )
    return chart.properties(height=alt.Step(28) if horizontal else 360)


main()
