"""How far the numbers can be trusted: the gate's checks, the records that couldn't be read, the files."""

import pandas as pd
import streamlit as st
from common import WHOLE, number, snapshot

lake, manifest, data = snapshot()
checks, rejected = data["checks"], data["rejected"]

st.title("Data quality")
st.caption("How far the numbers can be trusted: the quality checks, the unreadable records, and the files.")

errors = checks[checks["severity"] == "error"]
warnings = checks[(checks["severity"] == "warning") & ~checks["passed"]]
with st.container(horizontal=True):
    st.badge(f"All {len(errors)} error checks passed", icon=":material/check_circle:", color="green")
    if len(warnings):
        st.badge(
            f"{len(warnings)} warning{'s' * (len(warnings) != 1)}", icon=":material/warning:", color="orange"
        )
    else:
        st.badge("No warnings", icon=":material/check_circle:", color="green")
st.caption(
    "An error check stops the build when it fails, so this snapshot passed them all. A warning only "
    "reports a fact about Verra's data."
)

status = (
    checks["passed"]
    .map({True: "Passed", False: "Warning"})
    .where(checks["passed"] | (checks["severity"] == "warning"), "Failed")
)
table = checks.assign(
    status=status.map(lambda s: [s]),
    check=checks["check_name"].str[:1].str.upper() + checks["check_name"].str[1:],  # sentence case
    kind=checks["severity"].str.capitalize(),
).sort_values(["passed", "severity", "check_name"])
st.dataframe(
    table,
    column_order=["status", "check", "failing_rows", "failing_credits", "kind"],
    column_config={
        "status": st.column_config.MultiselectColumn(
            "Status", options=["Passed", "Warning", "Failed"], color=["green", "orange", "red"]
        ),
        "check": st.column_config.TextColumn("Check", width="large"),
        "failing_rows": number("Rows"),
        "failing_credits": number("Credits"),
        "kind": "Kind",
    },
    hide_index=True,
    alt="Every check of the quality gate, warnings first, with the rows and credits involved",
)

st.subheader("Records that couldn't be read")
if rejected.empty:
    st.caption("None: every record in the three files was read.")
else:
    st.caption(
        "Each is kept in bronze with the reason and its exact text, and counted in the warnings above."
    )
    st.dataframe(
        rejected,
        column_config={
            "file": "File",
            "line": st.column_config.NumberColumn("Line", format=WHOLE),
            "reason": st.column_config.TextColumn("Reason", width="large"),
            "raw_text": st.column_config.TextColumn("Exact text", width="large"),
        },
        hide_index=True,
        alt="The records that couldn't be read, with their file, line, reason and exact text",
    )

st.subheader("The files")
files = pd.DataFrame(
    [
        {
            "file": entry["file"],
            "rows": entry["rows_loaded"],
            "quarantined": entry["rows_quarantined"],
            "sha256": entry["sha256"][:12],
            "findings": "; ".join(entry["findings"]) or "Nothing unusual",
        }
        for entry in manifest["files"]
    ]
)
st.dataframe(
    files,
    column_config={
        "file": "File",
        "rows": number("Rows loaded"),
        "quarantined": number("Quarantined"),
        "sha256": st.column_config.TextColumn(
            "SHA-256", help="The first 12 characters of the file's checksum"
        ),
        "findings": st.column_config.TextColumn("What it looked like", width="large"),
    },
    hide_index=True,
    alt="Each raw file with its rows, checksum and what was unusual about it",
)
