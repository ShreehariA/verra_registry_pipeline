import dataclasses

import pytest

from tests.verra_files import RETIREMENT_HEADER
from verra_pipeline.errors import SchemaMismatchError
from verra_pipeline.ingest.header import HeaderMatch, HeaderMatcher
from verra_pipeline.schema import SchemaRegistry, TableSpec

FILE = "VerraRetirements_2030-01-15.csv"


def match(header: tuple[str, ...], table: TableSpec) -> HeaderMatch:
    return HeaderMatcher().match(header, table, FILE)


@pytest.fixture
def retirements(registry: SchemaRegistry) -> TableSpec:
    return registry.table("bronze", "retirements")


def with_alias(table: TableSpec, column: str, alias: str) -> TableSpec:
    columns = tuple(
        dataclasses.replace(c, aliases=(alias,)) if c.name == column else c for c in table.columns
    )
    return dataclasses.replace(table, columns=columns)


def test_matches_every_real_header_to_its_schema_column(retirements: TableSpec) -> None:
    result = match(RETIREMENT_HEADER, retirements)

    assert result.positions["retirement_qty"] == RETIREMENT_HEADER.index("Retirement QTY")
    assert len(result.positions) == len(RETIREMENT_HEADER)
    assert result.extra_columns == ()
    assert result.missing_optional == ()


def test_matches_by_name_in_any_order(retirements: TableSpec) -> None:
    result = match(tuple(reversed(RETIREMENT_HEADER)), retirements)

    assert result.positions["program"] == len(RETIREMENT_HEADER) - 1


def test_an_alias_in_the_schema_accepts_a_renamed_header(retirements: TableSpec) -> None:
    renamed = tuple("Quantity Retired" if h == "Retirement QTY" else h for h in RETIREMENT_HEADER)

    result = match(renamed, with_alias(retirements, "retirement_qty", "Quantity Retired"))

    assert result.positions["retirement_qty"] == RETIREMENT_HEADER.index("Retirement QTY")


def test_a_missing_required_column_stops_the_run_and_names_its_header(retirements: TableSpec) -> None:
    header = tuple(h for h in RETIREMENT_HEADER if h != "Retirement QTY")

    with pytest.raises(SchemaMismatchError, match=r"retirement_qty \(header 'Retirement QTY'\)"):
        match(header, retirements)


def test_a_missing_optional_column_is_reported_not_fatal(retirements: TableSpec) -> None:
    result = match(tuple(h for h in RETIREMENT_HEADER if h != "Region"), retirements)

    assert result.missing_optional == ("region",)


def test_a_column_the_schema_does_not_know_is_kept(retirements: TableSpec) -> None:
    result = match((*RETIREMENT_HEADER, "Corresponding Adjustment"), retirements)

    assert result.extra_columns == (("corresponding_adjustment", len(RETIREMENT_HEADER)),)


def test_an_unknown_column_named_like_a_schema_column_gets_a_prefix(retirements: TableSpec) -> None:
    renamed = tuple(
        dataclasses.replace(c, name="quantity") if c.name == "retirement_qty" else c
        for c in retirements.columns
    )
    table = dataclasses.replace(retirements, columns=renamed)

    result = match((*RETIREMENT_HEADER, "Quantity"), table)

    assert result.positions["quantity"] == RETIREMENT_HEADER.index("Retirement QTY")
    assert result.extra_columns[0][0] == "extra_quantity"


def test_two_headers_feeding_one_column_stop_the_run(retirements: TableSpec) -> None:
    with pytest.raises(SchemaMismatchError, match="two headers feed the column vintage"):
        match((*RETIREMENT_HEADER, "VINTAGE"), retirements)


def test_a_repeated_unknown_header_stops_the_run(retirements: TableSpec) -> None:
    with pytest.raises(SchemaMismatchError, match="appear more than once: notes"):
        match((*RETIREMENT_HEADER, "Notes", "notes"), retirements)


def test_a_blank_header_cell_is_named_by_its_position(retirements: TableSpec) -> None:
    result = match((*RETIREMENT_HEADER, ""), retirements)

    assert result.extra_columns == ((f"unnamed_{len(RETIREMENT_HEADER) + 1}", len(RETIREMENT_HEADER)),)
