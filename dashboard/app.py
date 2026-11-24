"""The dashboard: the brief's three questions, how far the numbers can be trusted, and SQL on every table.

Run it with `make dashboard`. It shows the newest finished snapshot in the lake of pipeline.toml, or in
$VERRA_LAKE when that is set (the cloud demo mounts the bucket there). Each page has its own address, and
what the pages share is in common.py.
"""

import streamlit as st
from common import lake_path

from verra_pipeline import PipelineError
from verra_pipeline.lake import newest_manifest

st.set_page_config(page_title="Verra registry", page_icon=":material/forest:", layout="wide")
try:
    newest_manifest(lake_path())
except PipelineError as error:
    st.error(str(error))
    st.stop()

st.navigation(
    [
        st.Page(
            "app_pages/overview.py",
            title="Overview",
            icon=":material/home:",
            default=True,
            help="Every credit Verra has issued and what happened to it, then the three answers.",
        ),
        st.Page(
            "app_pages/projects.py",
            title="Projects",
            icon=":material/forest:",
            help="Question 1: issued, retired, cancelled and available for every project. Find one to see "
            "its vintages and who retired its credits.",
        ),
        st.Page(
            "app_pages/vintages.py",
            title="Vintages",
            icon=":material/calendar_month:",
            help="Question 2: credit activity by vintage, in credits or as a share of what was issued.",
        ),
        st.Page(
            "app_pages/retirers.py",
            title="Retirers",
            icon=":material/corporate_fare:",
            help="Question 3: who retires the most, and what. Pick an owner to see the projects behind them.",
        ),
        st.Page(
            "app_pages/over_time.py",
            title="Over time",
            icon=":material/timeline:",
            help="Credits issued, retired and cancelled per year, or as running totals.",
        ),
        st.Page(
            "app_pages/data_quality.py",
            title="Data quality",
            icon=":material/fact_check:",
            help="The quality gate's checks, the records that couldn't be read, and the files.",
        ),
        st.Page(
            "app_pages/sql.py",
            title="SQL",
            icon=":material/database:",
            help="Any query on any table, raw rows included, read-only. Browse the tables, see their columns "
            "and profile, and keep a history of your queries.",
        ),
    ],
    position="top",
).run()
