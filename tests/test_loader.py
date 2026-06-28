from datetime import datetime

import pandas as pd

import pipeline.loader as loader


def _seed_data(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(loader, "LIST_SIZE_PARQUET_PATH", tmp_path / "list_size.parquet")
    monkeypatch.setattr(loader, "MAPPING_PARQUET_PATH", tmp_path / "mapping.parquet")

    list_size = pd.DataFrame(
        [
            {
                "SNAPSHOT_DATE": datetime(2025, 1, 1),
                "CODE": "A1",
                "NUMBER_OF_PATIENTS": 100,
                "DATA_SOURCE": "PDS",
            },
            {
                "SNAPSHOT_DATE": datetime(2025, 1, 1),
                "CODE": "A2",
                "NUMBER_OF_PATIENTS": 200,
                "DATA_SOURCE": "PDS",
            },
        ]
    )
    mapping = pd.DataFrame(
        [
            {
                "SNAPSHOT_DATE": datetime(2025, 1, 1),
                "PRACTICE_CODE": "A1",
                "PRACTICE_NAME": "Practice A1",
                "COMM_REGION_NAME": "London",
                "SUPPLIER_NAME": "TPP",
                "CLINICAL_SYSTEM": "SystmOne",
            },
            {
                "SNAPSHOT_DATE": datetime(2025, 1, 1),
                "PRACTICE_CODE": "A2",
                "PRACTICE_NAME": "Practice A2",
                "COMM_REGION_NAME": "London",
                "SUPPLIER_NAME": "EMIS",
                "CLINICAL_SYSTEM": "EMIS Web",
            },
        ]
    )

    loader.upsert_month(list_size, mapping)


def test_query_returns_rows(tmp_path, monkeypatch) -> None:
    _seed_data(tmp_path, monkeypatch)
    result = loader.query("SELECT COUNT(*) AS c FROM list_size")
    assert int(result.iloc[0]["c"]) == 2


def test_list_size_ts_filter(tmp_path, monkeypatch) -> None:
    _seed_data(tmp_path, monkeypatch)
    result = loader.get_list_size_ts("A1")
    assert len(result) == 1
    assert result.iloc[0]["CODE"] == "A1"


def test_market_share_ts_returns_share_columns(tmp_path, monkeypatch) -> None:
    _seed_data(tmp_path, monkeypatch)
    result = loader.get_market_share_ts("London")
    assert {"PRACTICE_SHARE", "PATIENT_SHARE"}.issubset(result.columns)
    assert len(result) == 2


def test_latest_snapshot_returns_joined_rows(tmp_path, monkeypatch) -> None:
    _seed_data(tmp_path, monkeypatch)
    result = loader.get_latest_snapshot()
    assert len(result) == 2
    assert "PRACTICE_NAME" in result.columns
