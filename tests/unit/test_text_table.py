from verra_pipeline.text_table import format_table


def test_pads_columns_and_right_aligns_numbers() -> None:
    table = format_table(("entity", "rows"), [("issuances", 2724), ("cancellations", 471)])

    assert table.splitlines() == [
        "entity         rows",
        "-------------  ----",
        "issuances      2724",
        "cancellations   471",
    ]


def test_right_aligns_preformatted_numbers_when_asked() -> None:
    table = format_table(("entity", "rows"), [("issuances", "2,724"), ("x", "471")], right_aligned={1})

    assert table.splitlines()[-1] == "x            471"


def test_shows_missing_values_and_keeps_line_breaks_on_one_line() -> None:
    table = format_table(("owner", "details"), [(None, "for Acme\nin 2010")])

    assert table.splitlines()[-1] == "NULL   for Acme\\nin 2010"
