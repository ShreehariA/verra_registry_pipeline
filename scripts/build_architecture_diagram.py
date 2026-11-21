#!/usr/bin/env python3
"""Write docs/architecture/verra-pipeline.drawio (draw.io / mxGraph XML).

Two diagrams, one per page:
  1. Data: the medallion layers and the process between each pair of layers.
  2. Infra: the Google Cloud services that run it and how they connect.

Drawing rules:
  - black on white only
  - standard shapes: rectangle = process or service, cylinder = data store,
    document = file, stick figure = user, dashed frame = boundary
  - solid arrow = data flow, dashed arrow = trigger or control
  - every connector has a fixed route, so no two connectors cross

Check the output after every change:
    python3 scripts/check_drawio.py docs/architecture/verra-pipeline.drawio
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs" / "architecture" / "verra-pipeline.drawio"
VERSION = "v0.3 · 2026-11-21 · draft for review"

BLACK, WHITE = "#000000", "#FFFFFF"
FONT = f"fontFamily=Helvetica;fontColor={BLACK};"
SHAPE = f"html=1;whiteSpace=wrap;fillColor={WHITE};strokeColor={BLACK};strokeWidth=1;{FONT}"
DASHED = "dashed=1;dashPattern=6 4;"

STYLE = {
    "service": "rounded=0;" + SHAPE + "fontSize=12;",
    "store": "shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=8;" + SHAPE + "fontSize=12;",
    "external_file": "shape=document;boundedLbl=1;size=0.15;" + DASHED + SHAPE + "fontSize=12;",
    "actor": "shape=umlActor;outlineConnect=0;labelPosition=right;verticalLabelPosition=middle;"
             "align=left;verticalAlign=middle;spacingLeft=6;" + SHAPE + "fontSize=12;",
    "boundary": f"rounded=1;arcSize=2;html=1;whiteSpace=wrap;fillColor=none;strokeColor={BLACK};strokeWidth=1;"
                + DASHED + FONT + "fontSize=12;fontStyle=1;align=left;verticalAlign=top;spacingLeft=10;spacingTop=4;",
    "frame": "rounded=0;" + SHAPE + "fontSize=11;align=left;verticalAlign=top;spacingLeft=8;spacingTop=4;",
    "title": f"text;html=1;whiteSpace=wrap;fillColor=none;strokeColor=none;{FONT}fontSize=18;fontStyle=1;"
             "align=left;verticalAlign=top;",
    "text": f"text;html=1;whiteSpace=wrap;fillColor=none;strokeColor=none;{FONT}fontSize=11;"
            "align=left;verticalAlign=middle;",
}
STYLE["mini_store"] = STYLE["store"].replace("size=8;", "size=4;")

EDGE_BASE = (f"edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor={BLACK};strokeWidth=1;"
             f"{FONT}fontSize=10;labelBackgroundColor={WHITE};")
EDGE_STYLE = {
    "data": EDGE_BASE + "endArrow=block;endFill=1;startArrow=none;",
    "both": EDGE_BASE + "endArrow=block;endFill=1;startArrow=block;startFill=1;",
    "control": EDGE_BASE + "dashed=1;dashPattern=4 3;endArrow=open;endFill=0;startArrow=none;",
}

# Connection points on a shape, as draw.io (x, y) fractions of its box.
LEFT, RIGHT, TOP, BOTTOM = (0, 0.5), (1, 0.5), (0.5, 0), (0.5, 1)


class Page:
    def __init__(self, page_id: str, name: str, width: int, height: int) -> None:
        self.page_id, self.name, self.width, self.height = page_id, name, width, height
        self.cells: list[tuple] = []

    def box(self, cid, label, x, y, w, h, kind):
        self.cells.append(("vertex", cid, label, STYLE[kind], (x, y, w, h)))
        return cid

    def link(self, cid, label, source, target, exit_pt, entry_pt, kind="data", via=(), label_at=0.0):
        """Connector with pinned ends; label_at runs from -1 (source end) to 1 (target end)."""
        style = (EDGE_STYLE[kind]
                 + f"exitX={exit_pt[0]};exitY={exit_pt[1]};exitDx=0;exitDy=0;"
                 + f"entryX={entry_pt[0]};entryY={entry_pt[1]};entryDx=0;entryDy=0;")
        self.cells.append(("edge", cid, label, style, (source, target, list(via), label_at)))

    def sample_line(self, cid, x1, y, x2, kind):
        """A short unattached arrow, used in the legend."""
        self.cells.append(("free_edge", cid, "", EDGE_STYLE[kind], ((x1, y), (x2, y))))

    def to_xml(self, parent: ET.Element) -> None:
        diagram = ET.SubElement(parent, "diagram", id=self.page_id, name=self.name)
        model = ET.SubElement(diagram, "mxGraphModel", dx="1600", dy="1000", grid="1", gridSize="10",
                              guides="1", tooltips="1", connect="1", arrows="1", fold="1", page="1",
                              pageScale="1", pageWidth=str(self.width), pageHeight=str(self.height),
                              background=WHITE, math="0", shadow="0")
        root = ET.SubElement(model, "root")
        ET.SubElement(root, "mxCell", id="0")
        ET.SubElement(root, "mxCell", id="1", parent="0")
        for kind, cid, label, style, geo in self.cells:
            if kind == "vertex":
                cell = ET.SubElement(root, "mxCell", id=cid, value=label, style=style, vertex="1", parent="1")
                x, y, w, h = geo
                ET.SubElement(cell, "mxGeometry", x=str(x), y=str(y), width=str(w), height=str(h),
                              **{"as": "geometry"})
            elif kind == "edge":
                source, target, via, label_at = geo
                cell = ET.SubElement(root, "mxCell", id=cid, value=label, style=style, edge="1",
                                     parent="1", source=source, target=target)
                attrs = {"relative": "1", "as": "geometry"}
                if label_at:
                    attrs["x"] = str(label_at)
                g = ET.SubElement(cell, "mxGeometry", **attrs)
                if via:
                    points = ET.SubElement(g, "Array", **{"as": "points"})
                    for px, py in via:
                        ET.SubElement(points, "mxPoint", x=str(px), y=str(py))
            else:  # free_edge
                (x1, y1), (x2, y2) = geo
                cell = ET.SubElement(root, "mxCell", id=cid, value=label, style=style, edge="1", parent="1")
                g = ET.SubElement(cell, "mxGeometry", width="50", height="50", relative="1",
                                  **{"as": "geometry"})
                ET.SubElement(g, "mxPoint", x=str(x1), y=str(y1), **{"as": "sourcePoint"})
                ET.SubElement(g, "mxPoint", x=str(x2), y=str(y2), **{"as": "targetPoint"})


def title(page: Page, heading: str) -> None:
    page.box(f"{page.page_id}-title", heading, 40, 20, 600, 30, "title")
    page.box(f"{page.page_id}-subtitle", VERSION, 40, 56, 400, 20, "text")


# Legend samples: (style, sample width, sample height); None = a short arrow.
SAMPLES = {
    "service": ("service", 36, 20), "store": ("mini_store", 36, 24), "external_file": ("external_file", 36, 24),
    "actor": ("actor", 10, 24), "boundary": ("boundary", 36, 20), "data": None, "control": None,
}


def legend(page: Page, right: int, top: int, items: list[tuple[str, str]]) -> None:
    """One-row legend whose right edge sits at `right`."""
    pad, after_sample, between, arrow = 14, 6, 18, 40

    def text_w(text):                      # generous estimate for 11 pt Helvetica
        return int(len(text) * 6.4) + 6

    width = pad + 52 + pad
    for kind, text in items:
        sample = SAMPLES[kind]
        width += between + (arrow if sample is None else sample[1]) + after_sample + text_w(text)
    x, mid = right - width, top + 32
    page.box(f"{page.page_id}-legend", "", x, top, width, 64, "frame")
    page.box(f"{page.page_id}-legend-title", "<b>Legend</b>", x + pad, mid - 10, 52, 20, "text")
    x += pad + 52
    for kind, text in items:
        sample = SAMPLES[kind]
        cid = f"{page.page_id}-legend-{kind}"
        x += between
        if sample is None:
            page.sample_line(cid, x, mid, x + arrow, kind)
            x += arrow
        else:
            style, w, h = sample
            page.box(cid, "", x, mid - h // 2, w, h, style)
            x += w
        x += after_sample
        page.box(f"{cid}-text", text, x, mid - 10, text_w(text), 20, "text")
        x += text_w(text)


# ---------------------------------------------------------------- page 1: data
def data_page() -> Page:
    p = Page("data", "1 · Data", 1700, 520)
    title(p, "Verra Registry Pipeline — data architecture")
    legend(p, right=1660, top=20, items=[("service", "Process"), ("store", "Data layer"),
                                         ("external_file", "Source files"), ("actor", "User"),
                                         ("data", "Data flow")])

    W, H, MAIN, BRANCH = 130, 80, 140, 290
    x = {"verra": 40, "landing": 210, "ingest": 380, "bronze": 550, "clean": 720, "silver": 890,
         "model": 1060, "gold": 1230, "use": 1400}

    def at(name, label, kind, y=MAIN):
        return p.box(name, label, x[name], y, W, H, kind)

    at("verra", "Verra Registry<br>daily export<br>3 CSV files", "external_file")
    at("landing", "<b>Landing</b><br>raw CSV files<br>never changed", "store")
    at("ingest", "<b>Ingest</b><br>check all 3 files<br>parse every row", "service")
    at("bronze", "<b>Bronze</b><br>rows as delivered<br>+ source line", "store")
    at("clean", "<b>Clean</b><br>fix types · dedupe<br>normalise to 3NF", "service")
    at("silver", "<b>Silver</b><br>clean tables<br>in 3NF", "store")
    at("model", "<b>Model + check</b><br>star schema<br>quality gate", "service")
    at("gold", "<b>Gold</b><br>star schema<br>+ summary tables", "store")
    at("use", "<b>Dashboards</b><br>and SQL", "service")
    p.box("analysts", "Analysts", x["use"] + W + 40, MAIN + 5, 30, 70, "actor")

    # Two side outputs: rows that fail parsing, and the results of the quality checks.
    p.box("quarantine", "<b>Quarantine</b><br>rejected rows<br>+ reason", x["ingest"], BRANCH, W, H, "store")
    p.box("quality", "<b>Quality results</b><br>every check<br>and its counts", x["model"], BRANCH, W, H, "store")

    chain = ["verra", "landing", "ingest", "bronze", "clean", "silver", "model", "gold", "use", "analysts"]
    for a, b in zip(chain, chain[1:]):
        p.link(f"{a}-{b}", "", a, b, RIGHT, LEFT)
    p.link("bad-rows", "bad rows", "ingest", "quarantine", BOTTOM, TOP)
    p.link("checks", "results", "model", "quality", BOTTOM, TOP)

    p.box("data-note", "<b>Medallion data architecture</b>: landing → bronze → silver → gold &nbsp;·&nbsp; "
          "every layer is kept per snapshot date, so a re-run replaces only its own copy &nbsp;·&nbsp; "
          "gold is published only when the quality gate passes", 40, 410, 1620, 50, "service")
    return p


# ---------------------------------------------------------------- page 2: infra
def infra_page() -> Page:
    p = Page("infra", "2 · Infra", 1654, 880)
    title(p, "Verra Registry Pipeline — infrastructure (Google Cloud)")
    legend(p, right=1620, top=20, items=[("service", "Service"), ("store", "Data store"),
                                         ("external_file", "External file"), ("actor", "User"),
                                         ("data", "Data flow"), ("control", "Trigger"),
                                         ("boundary", "Boundary")])

    W, H = 170, 70
    col = {1: 40, 2: 340, 3: 610, 4: 880, 5: 1150, 6: 1420}
    row = {1: 140, 2: 300, 3: 460, 4: 620}

    def cx(c):
        return col[c] + W // 2

    def cy(r):
        return row[r] + H // 2

    def at(c, r, cid, label, kind):
        return p.box(cid, label, col[c], row[r], W, H, kind)

    p.box("gcp", "Google Cloud project · us-central1", 300, 100, 1060, 630, "boundary")

    at(1, 2, "src", "Verra Registry<br>daily export (3 CSVs)", "external_file")
    at(2, 1, "eventarc", "<b>Eventarc</b><br>new-file trigger", "service")
    at(2, 2, "landing", "<b>Cloud Storage</b><br>landing bucket", "store")
    at(3, 1, "workflows", "<b>Cloud Workflows</b><br>runs the steps in order", "service")
    at(3, 2, "jobs", "<b>Cloud Run jobs</b><br>pipeline container", "service")
    at(3, 3, "lake", "<b>Cloud Storage</b><br>data lake<br>bronze · silver · gold", "store")
    at(4, 2, "firestore", "<b>Firestore</b><br>run status<br>file locations", "store")
    at(4, 3, "bigquery", "<b>BigQuery</b><br>warehouse (gold)", "store")
    at(5, 3, "streamlit", "<b>Cloud Run</b><br>Streamlit dashboard", "service")
    at(5, 4, "looker", "<b>Looker Studio</b><br>reports", "service")
    p.box("people", "Analysts", cx(6) - 15, row[3], 30, H, "actor")

    p.link("i-drop", "daily files", "src", "landing", RIGHT, LEFT, label_at=-0.31)  # label outside the frame
    p.link("i-new", "new file", "landing", "eventarc", TOP, BOTTOM, kind="control")
    p.link("i-start", "start", "eventarc", "workflows", RIGHT, LEFT, kind="control")
    p.link("i-run", "run", "workflows", "jobs", BOTTOM, TOP, kind="control")
    p.link("i-read", "read", "landing", "jobs", RIGHT, LEFT)
    p.link("i-lake", "read / write", "jobs", "lake", BOTTOM, TOP, kind="both")
    p.link("i-status", "status", "jobs", "firestore", RIGHT, LEFT)
    p.link("i-load", "load gold", "lake", "bigquery", RIGHT, LEFT)
    p.link("i-dash", "", "bigquery", "streamlit", RIGHT, LEFT)
    p.link("i-looker", "", "bigquery", "looker", BOTTOM, LEFT, via=[(cx(4), cy(4))])
    p.link("i-use1", "", "streamlit", "people", RIGHT, LEFT)
    p.link("i-use2", "", "looker", "people", RIGHT, BOTTOM, via=[(cx(6), cy(4))])

    p.box("infra-note", "<b>Infrastructure</b>: Terraform &nbsp;·&nbsp; <b>Security</b>: IAM, one least-privilege "
          "service account per service &nbsp;·&nbsp; <b>CI/CD</b>: GitHub Actions builds, tests and deploys",
          40, 770, 1580, 50, "service")
    return p


def main() -> None:
    mxfile = ET.Element("mxfile", host="drawio", version="24.7.17", type="device")
    for page in (data_page(), infra_page()):
        page.to_xml(mxfile)
    ET.indent(mxfile, space="  ")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(ET.tostring(mxfile, encoding="unicode") + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
