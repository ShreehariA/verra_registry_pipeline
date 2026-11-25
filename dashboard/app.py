"""The dashboard, on the newest build in the lake of pipeline.toml, or in $VERRA_LAKE when that is set."""

from pathlib import Path

import streamlit as st
from common import lake_path

from verra_pipeline import PipelineError
from verra_pipeline.lake import newest_manifest

# a local tab icon: a Material icon, here or on a page, is fetched from Google on every page load
ICON = Path(__file__).parent / "static" / "favicon.png"
st.set_page_config(page_title="Verra registry", page_icon=str(ICON), layout="wide")
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
            help="Every credit issued, and what happened to it.",
        ),
        st.Page(
            "app_pages/projects.py",
            title="Projects",
            icon=":material/forest:",
            help="Question 1: each project's credits issued, retired, cancelled and available.",
        ),
        st.Page(
            "app_pages/vintages.py",
            title="Vintages",
            icon=":material/calendar_month:",
            help="Question 2: credit activity by vintage.",
        ),
        st.Page(
            "app_pages/retirers.py",
            title="Retirers",
            icon=":material/corporate_fare:",
            help="Question 3: who retires the most, and what.",
        ),
        st.Page(
            "app_pages/over_time.py",
            title="Over time",
            icon=":material/timeline:",
            help="Credits issued, retired and cancelled per year.",
        ),
        st.Page(
            "app_pages/data_quality.py",
            title="Data quality",
            icon=":material/fact_check:",
            help="The quality checks, and the records that couldn't be read.",
        ),
        st.Page(
            "app_pages/sql.py",
            title="SQL",
            icon=":material/database:",
            help="Query any table, read-only.",
        ),
    ],
    position="top",
).run()
