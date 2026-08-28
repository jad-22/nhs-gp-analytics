import pandas as pd

from dashboard.components.maps import practice_marker_map


def _practice_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "LATITUDE": 51.5,
                "LONGITUDE": -0.12,
                "IMD_DECILE": 1,
                "PRACTICE_NAME": "A Surgery",
                "CODE": "A81001",
                "NUMBER_OF_PATIENTS": 5000,
                "REGION_NAME": "London",
            },
            {
                "LATITUDE": 53.4,
                "LONGITUDE": -2.98,
                "IMD_DECILE": 9,
                "PRACTICE_NAME": "B Practice",
                "CODE": "B82002",
                "NUMBER_OF_PATIENTS": 12000,
                "REGION_NAME": "North West",
            },
            {
                "LATITUDE": None,
                "LONGITUDE": None,
                "IMD_DECILE": 5,
                "PRACTICE_NAME": "C Centre",
                "CODE": "C83003",
                "NUMBER_OF_PATIENTS": 800,
                "REGION_NAME": "South East",
            },
        ]
    )


def test_practice_marker_map_uses_maplibre_trace() -> None:
    # Plotly 6 removed Scattermapbox/layout.mapbox; the map must use the MapLibre subplot.
    fig = practice_marker_map(_practice_frame(), "Practice locations by IMD decile")

    assert fig.data[0].type == "scattermap"
    assert fig.layout.map.style == "open-street-map"
    assert fig.layout.map.zoom == 5
    # Practices without a geocoded postcode are dropped rather than plotted at (0, 0).
    assert len(fig.data[0].lat) == 2
    assert fig.to_html(include_plotlyjs=False)


def test_practice_marker_map_handles_empty_and_unmapped_frames() -> None:
    for frame in (pd.DataFrame(), _practice_frame().assign(LATITUDE=None, LONGITUDE=None)):
        fig = practice_marker_map(frame, "Practice locations by IMD decile")
        assert fig.data == ()
        assert fig.layout.annotations[0].text == "No mapped practices for the selected filters."
