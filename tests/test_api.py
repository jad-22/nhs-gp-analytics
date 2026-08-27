"""Tests for the public API.

Built against a small synthetic serving database rather than the real one, so they run
anywhere and assert behaviour rather than this month's numbers. What they mostly guard
is the contract a public consumer depends on: stable error shapes, honest forecast
metadata, and caching headers that actually work.
"""

from __future__ import annotations

import duckdb
import pandas as pd
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

RUN_ID = "2026-06.abcdef123456"
GENERATED_AT = pd.Timestamp("2026-08-04T02:14:00Z")
TRAINED_THROUGH = pd.Timestamp("2026-06-01")


def _months(count: int) -> pd.DatetimeIndex:
    return pd.date_range("2020-01-01", periods=count, freq="MS")


def _serving_db(path) -> None:
    """A miniature of the real database: 2 practices (1 closed), 1 of each aggregate."""

    history = _months(78)
    practices = pd.DataFrame(
        [
            {
                "ODS_CODE": "A81001",
                "PRACTICE_NAME": "Alpha Surgery",
                "PRACTICE_POSTCODE": "TS1 1AA",
                "PCN_CODE": "U00001",
                "PCN_NAME": "Alpha PCN",
                "ICB_CODE": "QHM",
                "ICB_NAME": "Alpha ICB",
                "REGION_CODE": "Y61",
                "REGION_NAME": "Alpha Region",
                "CLINICAL_SYSTEM": "EMIS",
                "SUPPLIER_NAME": "EMIS Health",
                "IMD_SCORE": 22.5,
                "IMD_DECILE": 4.0,
                "LATITUDE": 54.5,
                "LONGITUDE": -1.2,
                "NUMBER_OF_PATIENTS": 3781,
                "DATA_SOURCE": "PDS",
                "ACTIVE": True,
                "FIRST_MONTH": history[0],
                "LAST_MONTH": history[-1],
                "AS_OF": history[-1],
            },
            {
                "ODS_CODE": "B82002",
                "PRACTICE_NAME": "Beta Surgery (closed)",
                "PRACTICE_POSTCODE": "LS1 1BB",
                "PCN_CODE": "U00001",
                "PCN_NAME": "Alpha PCN",
                "ICB_CODE": "QHM",
                "ICB_NAME": "Alpha ICB",
                "REGION_CODE": "Y61",
                "REGION_NAME": "Alpha Region",
                "CLINICAL_SYSTEM": "TPP",
                "SUPPLIER_NAME": "TPP",
                "IMD_SCORE": 31.0,
                "IMD_DECILE": 2.0,
                "LATITUDE": 53.8,
                "LONGITUDE": -1.5,
                "NUMBER_OF_PATIENTS": None,
                "DATA_SOURCE": None,
                "ACTIVE": False,
                "FIRST_MONTH": history[0],
                "LAST_MONTH": history[40],
                "AS_OF": history[-1],
            },
        ]
    )

    list_size = pd.concat(
        [
            pd.DataFrame(
                {
                    "SNAPSHOT_DATE": history,
                    "CODE": "A81001",
                    "NUMBER_OF_PATIENTS": range(3700, 3700 + len(history)),
                    "DATA_SOURCE": "PDS",
                }
            ),
            pd.DataFrame(
                {
                    "SNAPSHOT_DATE": history[:41],
                    "CODE": "B82002",
                    "NUMBER_OF_PATIENTS": range(2000, 2000 + 41),
                    "DATA_SOURCE": "NHAIS",
                }
            ),
        ],
        ignore_index=True,
    )

    aggregates = pd.concat(
        [
            pd.DataFrame(
                {
                    "LEVEL": level,
                    "ENTITY_CODE": code,
                    "SNAPSHOT_DATE": history,
                    "NUMBER_OF_PATIENTS": range(5700, 5700 + len(history)),
                }
            )
            for level, code in (("national", "ENG"), ("region", "Y61"), ("icb", "QHM"), ("pcn", "U00001"))
        ],
        ignore_index=True,
    )

    entities = pd.DataFrame(
        [
            {"LEVEL": "national", "ENTITY_CODE": "ENG", "ENTITY_NAME": "England", "PRACTICE_COUNT": 1, "LATEST_PATIENTS": 5777, "AS_OF": history[-1]},
            {"LEVEL": "region", "ENTITY_CODE": "Y61", "ENTITY_NAME": "Alpha Region", "PRACTICE_COUNT": 1, "LATEST_PATIENTS": 5777, "AS_OF": history[-1]},
            {"LEVEL": "icb", "ENTITY_CODE": "QHM", "ENTITY_NAME": "Alpha ICB", "PRACTICE_COUNT": 1, "LATEST_PATIENTS": 5777, "AS_OF": history[-1]},
            {"LEVEL": "pcn", "ENTITY_CODE": "U00001", "ENTITY_NAME": "Alpha PCN", "PRACTICE_COUNT": 1, "LATEST_PATIENTS": 5777, "AS_OF": history[-1]},
        ]
    )

    def _forecast(level: str, code: str, name: str, model: str, calibrated: bool = True) -> pd.DataFrame:
        future = pd.date_range("2026-07-01", periods=12, freq="MS")
        return pd.DataFrame(
            {
                "LEVEL": level,
                "ENTITY_CODE": code,
                "ENTITY_NAME": name,
                "DS": future,
                "HORIZON_MONTH": range(1, 13),
                "YHAT": [3800.0 + step for step in range(12)],
                "YHAT_LOWER": [3700.0 + step for step in range(12)],
                "YHAT_UPPER": [3900.0 + step for step in range(12)],
                "MODEL": model,
                "CALIBRATED": calibrated,
                "INTERVAL_LEVEL": 0.8,
                "TRAINED_THROUGH": TRAINED_THROUGH,
                "RUN_ID": RUN_ID,
                "GENERATED_AT": GENERATED_AT,
            }
        )

    forecasts = pd.concat(
        [
            _forecast("practice", "A81001", "Alpha Surgery", "autoets"),
            _forecast("national", "ENG", "England", "holt_winters"),
            _forecast("region", "Y61", "Alpha Region", "holt_winters"),
            _forecast("icb", "QHM", "Alpha ICB", "holt_winters"),
            _forecast("pcn", "U00001", "Alpha PCN", "autoets", calibrated=False),
        ],
        ignore_index=True,
    )

    def _metric(level: str, code: str, model: str, mase: float, calibrated=True, quarantined=False, reason="") -> dict:
        return {
            "LEVEL": level,
            "ENTITY_CODE": code,
            "ENTITY_NAME": code,
            "MODEL": model,
            "CALIBRATED": calibrated,
            "N_MONTHS": 78,
            "N_FORECASTS": 72,
            "MAE": 40.0,
            "RMSE": 55.0,
            "MAPE": 0.019,
            "MASE": mase,
            "COVERAGE": 0.75,
            "COVERAGE_NATIVE": 0.66,
            "QUARANTINED": quarantined,
            "QUARANTINE_REASON": reason,
            "RUN_ID": RUN_ID,
        }

    metrics = pd.DataFrame(
        [
            _metric("practice", "A81001", "autoets", 0.52),
            # A practice whose history no model can track: metrics exist, forecast does not.
            _metric("practice", "C84077", "autoets", 72.4, quarantined=True, reason="mase_above_threshold"),
            _metric("national", "ENG", "holt_winters", 0.21),
            _metric("region", "Y61", "holt_winters", 0.20),
            _metric("icb", "QHM", "holt_winters", 0.27),
            _metric("pcn", "U00001", "autoets", 0.39, calibrated=False),
        ]
    )

    meta = pd.DataFrame(
        [
            {
                "RUN_ID": RUN_ID,
                "GENERATED_AT": GENERATED_AT,
                "TRAINED_THROUGH": TRAINED_THROUGH,
                "EARLIEST_MONTH": history[0],
                "LATEST_MONTH": history[-1],
                "PRACTICE_COUNT": 1,
                "PRACTICE_COUNT_ALL": 2,
                "ENTITY_COUNT": 4,
                "FORECAST_COUNT": 5,
                "QUARANTINED_COUNT": 1,
                "INTERVAL_LEVEL": 0.8,
                "MEASURED_COVERAGE": 0.75,
                "MEASURED_COVERAGE_NATIVE": 0.66,
                "MEDIAN_MASE": 0.39,
            }
        ]
    )

    connection = duckdb.connect(str(path))
    try:
        for name, frame in (
            ("practices", practices),
            ("list_size", list_size),
            ("aggregate_list_size", aggregates),
            ("entities", entities),
            ("forecasts", forecasts),
            ("forecast_metrics", metrics),
            ("meta", meta),
        ):
            connection.register(f"_{name}", frame)
            connection.execute(f"CREATE TABLE {name} AS SELECT * FROM _{name}")
        connection.execute("CHECKPOINT")
    finally:
        connection.close()


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    path = tmp_path_factory.mktemp("serving") / "serving.duckdb"
    _serving_db(path)

    from api import config, db

    config.SERVING_DB_PATH = path
    db.SERVING_DB_PATH = path
    db._connection = None
    db.meta.cache_clear()
    db.run_id.cache_clear()

    from api.main import app

    # Rate limits would otherwise trip partway through the suite.
    app.state.limiter.enabled = False
    with TestClient(app) as test_client:
        yield test_client


# --------------------------------------------------------------------------------------
# The core ask
# --------------------------------------------------------------------------------------


def test_practice_forecast_is_the_documented_shape(client):
    response = client.get("/v1/practices/A81001/forecast")

    assert response.status_code == 200
    body = response.json()
    assert body["entity_code"] == "A81001"
    assert body["entity_name"] == "Alpha Surgery"

    forecast = body["forecast"]
    assert forecast["model"] == "autoets"
    assert forecast["calibrated"] is True
    assert forecast["interval_warning"] is None
    assert forecast["trained_through"] == "2026-06-01"
    assert len(forecast["points"]) == 12
    assert [point["horizon_month"] for point in forecast["points"]] == list(range(1, 13))
    assert forecast["points"][0]["date"] == "2026-07-01"
    assert all(point["yhat_lower"] <= point["yhat"] <= point["yhat_upper"] for point in forecast["points"])

    # Accuracy travels with the forecast: a number without its error bar invites misuse.
    assert body["accuracy"]["mase"] == pytest.approx(0.52)
    # Both coverages travel with the forecast: the one the served band achieved, and the
    # model's own band for comparison. Confusing them is the whole reason they are named.
    assert body["accuracy"]["coverage"] == pytest.approx(0.75)
    assert body["accuracy"]["coverage_native"] == pytest.approx(0.66)
    assert body["meta"]["run_id"] == RUN_ID
    assert "Open Government Licence" in body["meta"]["source"]


def test_lowercase_ods_code_resolves(client):
    assert client.get("/v1/practices/a81001/forecast").status_code == 200


def test_uncalibrated_forecast_says_so(client):
    body = client.get("/v1/pcns/U00001/forecast").json()

    assert body["forecast"]["calibrated"] is False
    assert "indicative only" in body["forecast"]["interval_warning"]


# --------------------------------------------------------------------------------------
# Failure modes a public consumer will hit
# --------------------------------------------------------------------------------------


def test_unknown_practice_is_a_clean_404(client):
    response = client.get("/v1/practices/ZZZ999")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "practice_not_found"
    assert "ZZZ999" in body["detail"]
    assert "Traceback" not in response.text


def test_closed_practice_keeps_history_but_has_no_forecast(client):
    history = client.get("/v1/practices/B82002/list-size")
    assert history.status_code == 200
    assert len(history.json()["points"]) == 41

    forecast = client.get("/v1/practices/B82002/forecast")
    assert forecast.status_code == 404
    body = forecast.json()
    assert body["code"] == "entity_closed"
    assert "history is still available" in body["detail"]


def test_quarantined_series_explains_itself(client):
    """A series withheld for being untrackable must say so, not 404 as if unknown."""

    from api import presenters
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as raised:
        presenters.forecast_response("practice", "C84077", "Pathological Surgery")

    assert raised.value.headers["X-Error-Code"] == "forecast_withheld"
    assert "too irregular" in raised.value.detail


def test_unknown_aggregate_is_a_clean_404(client):
    response = client.get("/v1/icbs/QZZ/forecast")

    assert response.status_code == 404
    assert response.json()["code"] == "icb_not_found"


def test_bad_pagination_is_a_422(client):
    assert client.get("/v1/practices?page=0").status_code == 422
    assert client.get("/v1/practices?page_size=100000").status_code == 422


# --------------------------------------------------------------------------------------
# Search, aggregates, history
# --------------------------------------------------------------------------------------


def test_search_and_filters(client):
    body = client.get("/v1/practices", params={"search": "alpha"}).json()
    assert [practice["ods_code"] for practice in body["practices"]] == ["A81001"]
    assert body["page"] == {"page": 1, "page_size": 50, "total": 1, "pages": 1}

    assert client.get("/v1/practices", params={"icb": "QHM"}).json()["page"]["total"] == 2
    assert client.get("/v1/practices", params={"icb": "QHM", "active": True}).json()["page"]["total"] == 1
    assert client.get("/v1/practices", params={"region": "Y61"}).json()["page"]["total"] == 2


def test_practice_attributes(client):
    body = client.get("/v1/practices/A81001").json()

    assert body["icb_code"] == "QHM"
    assert body["region_name"] == "Alpha Region"
    assert body["postcode"] == "TS1 1AA"
    assert body["patients"] == 3781
    assert body["active"] is True
    assert body["as_of"] == "2026-06-01"


def test_history_is_month_start_ascending(client):
    points = client.get("/v1/practices/A81001/list-size").json()["points"]

    assert len(points) == 78
    assert points[0]["date"] == "2020-01-01"
    assert points[-1]["date"] == "2026-06-01"
    assert points[0]["data_source"] == "PDS"


@pytest.mark.parametrize(
    ("path", "level"),
    [
        ("/v1/national/list-size", "national"),
        ("/v1/regions/Y61/list-size", "region"),
        ("/v1/icbs/QHM/list-size", "icb"),
        ("/v1/pcns/U00001/list-size", "pcn"),
    ],
)
def test_every_aggregate_level_serves_history(client, path, level):
    body = client.get(path).json()

    assert body["level"] == level
    assert len(body["points"]) == 78
    # data_source is null at aggregate level: the total spans practices whose months may
    # have come from different sources, so no single value is true of the row.
    assert body["points"][0]["data_source"] is None


@pytest.mark.parametrize("path", ["/v1/regions", "/v1/icbs", "/v1/pcns"])
def test_entity_listings(client, path):
    body = client.get(path).json()

    assert len(body["entities"]) == 1
    assert body["entities"][0]["practice_count"] == 1


# --------------------------------------------------------------------------------------
# Metadata and honesty
# --------------------------------------------------------------------------------------


def test_meta_publishes_measured_coverage_not_the_nominal_level(client):
    body = client.get("/v1/meta").json()

    assert body["interval_level"] == 0.8
    assert body["measured_coverage"] == pytest.approx(0.75)
    assert body["measured_coverage"] < body["interval_level"]
    assert body["run_id"] == RUN_ID
    assert body["practice_count"] == 1
    assert body["practice_count_all"] == 2
    assert body["quarantined_count"] == 1
    assert any("NHAIS" in caveat for caveat in body["caveats"])
    assert any("ghost patients" in caveat for caveat in body["caveats"])


def test_models_endpoint_documents_the_per_level_split(client):
    body = client.get("/v1/meta/models").json()

    by_level = {row["level"]: row for row in body["models"]}
    assert by_level["practice"]["model"] == "autoets"
    assert by_level["national"]["model"] == "holt_winters"
    assert by_level["practice"]["quarantined"] == 1
    assert "prophet" not in {row["model"] for row in body["models"]}
    assert any("Prophet is not used" in note for note in body["notes"])


def test_health_reports_the_vintage(client):
    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["run_id"] == RUN_ID


# --------------------------------------------------------------------------------------
# Caching
# --------------------------------------------------------------------------------------


def test_responses_carry_an_etag_and_long_cache_control(client):
    response = client.get("/v1/practices/A81001/forecast")

    assert response.headers["ETag"] == f'"{RUN_ID}"'
    assert "max-age=86400" in response.headers["Cache-Control"]
    assert "stale-while-revalidate" in response.headers["Cache-Control"]


def test_if_none_match_returns_304(client):
    etag = client.get("/v1/practices/A81001/forecast").headers["ETag"]

    response = client.get("/v1/practices/A81001/forecast", headers={"If-None-Match": etag})

    assert response.status_code == 304


def test_stale_etag_returns_the_body(client):
    response = client.get("/v1/practices/A81001/forecast", headers={"If-None-Match": '"2020-01.stale"'})

    assert response.status_code == 200


# --------------------------------------------------------------------------------------
# The spec itself
# --------------------------------------------------------------------------------------


def test_openapi_documents_the_licence_and_the_core_route(client):
    spec = client.get("/v1/openapi.json").json()

    assert spec["openapi"].startswith("3.1")
    assert spec["info"]["license"]["name"] == "Open Government Licence v3.0"
    forecast = spec["paths"]["/v1/practices/{ods_code}/forecast"]["get"]
    assert "404" in forecast["responses"]
    assert {"practices", "meta", "national"} <= {tag["name"] for tag in spec["tags"]}

    # The aggregate routes are generated in a loop, so they would otherwise all inherit
    # the same handler name and collide. Duplicate operationIds break client generators.
    operation_ids = [
        operation["operationId"]
        for path in spec["paths"].values()
        for operation in path.values()
        if "operationId" in operation
    ]
    assert len(operation_ids) == len(set(operation_ids)), sorted(operation_ids)


def test_docs_render(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200


def test_raw_sql_is_not_reachable_from_any_route(client):
    """pipeline.loader.query() takes raw SQL; nothing in api/ may import it.

    Checked on the parsed import graph rather than by text search, so a comment
    explaining the rule does not itself trip the rule.
    """

    import ast
    from pathlib import Path

    api_root = Path(__file__).resolve().parent.parent / "api"
    imported: set[str] = set()
    for path in api_root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
                imported.update(f"{node.module}.{alias.name}" for alias in node.names)

    assert not any(name.startswith("pipeline.loader") for name in imported), sorted(imported)
    # The only pipeline module the API may touch is config (paths and constants).
    assert {name for name in imported if name.startswith("pipeline")} <= {"pipeline", "pipeline.config"}
