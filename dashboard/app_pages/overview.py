"""Overview: every credit Verra has issued and what happened to it, then the three answers in a line each."""

from datetime import date

import streamlit as st
from common import PARTS, compact, ledger_bar, plain, snapshot

lake, manifest, data = snapshot()
credits = manifest["credits"]
day = date.fromisoformat(manifest["snapshot_date"])
balance, vintages, retirers, checks = data["balance"], data["vintages"], data["retirers"], data["checks"]

st.title("Verra registry")
st.caption(f"Every carbon credit Verra has issued, and what has happened to it, on {day.day} {day:%B %Y}.")

issued = credits["issued"]
st.metric("Credits issued", compact(issued), help=f"{issued:,} credits")
shares = [credits[part] / issued if issued else 0 for part in PARTS]
st.altair_chart(
    ledger_bar(credits),
    alt=f"Of {compact(issued)} credits issued, {shares[0]:.1%} are retired, {shares[1]:.1%} cancelled "
    f"and {shares[2]:.1%} still available.",
)

warnings = int((~checks["passed"] & (checks["severity"] == "warning")).sum())
with st.container(horizontal=True, vertical_alignment="center"):
    st.badge("Quality gate passed", icon=":material/check_circle:", color="green")
    st.badge(f"{warnings} warning{'s' * (warnings != 1)}", icon=":material/warning:", color="orange")
    st.page_link("app_pages/data_quality.py", label="See the checks")

st.space("medium")

# Question 1: how many projects, and how concentrated the credits are
largest = balance.nlargest(1, "issued")
projects = f"{len(balance):,} projects."
if len(largest) and issued:
    top = largest.iloc[0]
    projects += (
        f" The largest, {plain(top.project_name)}, holds {top.issued / issued:.0%} of every credit issued."
    )
st.page_link("app_pages/projects.py", label=f"**Projects.** {projects}", icon=":material/forest:")

# Question 2: how used the older vintages are against the newer, split where half the credits were issued
by_year = vintages.dropna(subset=["vintage_start"]).groupby("vintage_start")[["issued", *PARTS]].sum()
answer = "Credit activity by vintage."
if by_year["issued"].sum():
    middle = by_year.index[(by_year["issued"].cumsum() >= by_year["issued"].sum() / 2).argmax()]
    old, new = by_year[by_year.index < middle], by_year[by_year.index >= middle]
    if old["issued"].sum() and new["issued"].sum():
        used = [
            (part["retired"].sum() + part["cancelled"].sum()) / part["issued"].sum() for part in (old, new)
        ]
        answer = f"Vintages before {middle:.0f} are {used[0]:.0%} used; from {middle:.0f} on, {used[1]:.0%}."
st.page_link("app_pages/vintages.py", label=f"**Vintages.** {answer}", icon=":material/calendar_month:")

# Question 3: the largest named retirer, and how much names no owner at all
named = retirers.dropna(subset=["owner_rank"]).sort_values("owner_rank")
unnamed = retirers.loc[retirers["owner_key"] == "unspecified", "credits"].sum()
retired = retirers["credits"].sum()
answer = "No retirement in this snapshot names an owner."
if len(named):
    first = named.iloc[0]
    answer = f"{plain(first.owner_name)} retired the most: {first.owner_credits:,} credits."
if retired:
    answer += f" {unnamed / retired:.1%} of retired credits name no owner."
st.page_link("app_pages/retirers.py", label=f"**Retirers.** {answer}", icon=":material/corporate_fare:")

st.space("medium")
st.caption("Every number here can be traced to the lines of Verra's files it came from, on the SQL page.")
