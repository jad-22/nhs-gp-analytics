from datetime import date
from pathlib import Path

import pandas as pd

from pipeline.transformer import transform_list_size, transform_mapping


def test_transform_list_size_filters_to_gp_all_all(tmp_path: Path) -> None:
    source = tmp_path / "list.csv"
    pd.DataFrame(
        [
            {"CODE": "A1", "TYPE": "GP", "SEX": "ALL", "AGE": "ALL", "NUMBER_OF_PATIENTS": "100"},
            {"CODE": "A2", "TYPE": "GP", "SEX": "M", "AGE": "ALL", "NUMBER_OF_PATIENTS": "200"},
        ]
    ).to_csv(source, index=False)

    transformed = transform_list_size(source, date(2025, 1, 1))
    assert list(transformed["CODE"]) == ["A1"]
    assert int(transformed.iloc[0]["NUMBER_OF_PATIENTS"]) == 100
    assert transformed.iloc[0]["DATA_SOURCE"] == "PDS"


def test_transform_mapping_derives_clinical_system(tmp_path: Path) -> None:
    source = tmp_path / "mapping.csv"
    pd.DataFrame(
        [
            {"PRACTICE_CODE": "A1", "SUPPLIER_NAME": "TPP"},
            {"PRACTICE_CODE": "A2", "SUPPLIER_NAME": "EMIS"},
            {"PRACTICE_CODE": "A3", "SUPPLIER_NAME": "Vision"},
        ]
    ).to_csv(source, index=False)

    transformed = transform_mapping(source, date(2022, 12, 1))
    systems = dict(zip(transformed["PRACTICE_CODE"], transformed["CLINICAL_SYSTEM"]))
    assert systems["A1"] == "SystmOne"
    assert systems["A2"] == "EMIS Web"
    assert systems["A3"] == "Others"


def test_transform_list_size_handles_legacy_counts_schema(tmp_path: Path) -> None:
    source = tmp_path / "legacy_counts.csv"
    pd.DataFrame(
        [
            {"GP_PRACTICE_CODE": "A1", "TOTAL_ALL": "123"},
            {"GP_PRACTICE_CODE": "A2", "TOTAL_ALL": "456"},
        ]
    ).to_csv(source, index=False)

    transformed = transform_list_size(source, date(2015, 1, 1))
    assert set(transformed["CODE"]) == {"A1", "A2"}
    assert int(transformed[transformed["CODE"] == "A1"].iloc[0]["NUMBER_OF_PATIENTS"]) == 123
    assert transformed.iloc[0]["DATA_SOURCE"] == "NHAIS"
