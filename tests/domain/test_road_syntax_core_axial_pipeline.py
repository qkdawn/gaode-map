import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("AMAP_JS_API_KEY", "test-key")

from modules.road import core
from modules.road.metrics import build_road_orientation_analysis


def _sample_polygon():
    return [
        [112.9800, 28.1900],
        [112.9900, 28.1900],
        [112.9900, 28.2000],
        [112.9800, 28.2000],
        [112.9800, 28.1900],
    ]


def _sample_overpass_elements():
    return [
        {
            "type": "way",
            "id": 1,
            "tags": {"highway": "residential"},
            "geometry": [
                {"lon": 112.9800, "lat": 28.1900},
                {"lon": 112.9900, "lat": 28.1900},
            ],
        }
    ]


def _mock_shapegraph_csv() -> str:
    return (
        "x1,y1,x2,y2,Choice,Choice R600,Choice R800,Integration [HH],Integration [HH] R600,"
        "Integration [HH] R800,Connectivity,Control,Mean Depth\n"
        "112.9800,28.1900,112.9900,28.1900,1,1,1,1,1,1,2,1,1.5\n"
    )


def _patch_core_runtime(monkeypatch, call_log, fail_axial=False):
    monkeypatch.setattr(core, "_fetch_overpass_elements", lambda _query: _sample_overpass_elements())
    monkeypatch.setattr(core, "_resolve_depthmap_cli_path", lambda _override=None: "/usr/local/bin/depthmapXcli")

    def _fake_run_depthmap_cmd(cli_path, args, workdir, timeout_s):
        mode = ""
        if "-m" in args:
            mode = str(args[args.index("-m") + 1])
        call_log.append({"mode": mode, "args": list(args)})
        if mode == "AXIAL" and fail_axial:
            raise RuntimeError("mock axial failure")
        if mode == "EXPORT":
            out_path = Path(args[args.index("-o") + 1])
            out_path.write_text(_mock_shapegraph_csv(), encoding="utf-8")

    monkeypatch.setattr(core, "_run_depthmap_cmd", _fake_run_depthmap_cmd)


def test_axial_pipeline_sequence_and_flags(monkeypatch):
    call_log = []
    _patch_core_runtime(monkeypatch, call_log, fail_axial=False)

    result = core.analyze_road_syntax(
        polygon=_sample_polygon(),
        coord_type="wgs84",
        mode="walking",
        graph_model="axial",
        highway_filter="all",
        include_geojson=True,
        radii_m=[600, 800],
        use_arcgis_webgl=False,
    )

    modes = [entry["mode"] for entry in call_log]
    assert modes == ["IMPORT", "MAPCONVERT", "AXIAL", "EXPORT"]

    mapconvert_args = next(entry["args"] for entry in call_log if entry["mode"] == "MAPCONVERT")
    assert "-co" in mapconvert_args
    assert mapconvert_args[mapconvert_args.index("-co") + 1] == "axial"

    axial_args = next(entry["args"] for entry in call_log if entry["mode"] == "AXIAL")
    assert "-xa" in axial_args
    assert axial_args[axial_args.index("-xa") + 1] == "600,800,n"
    assert "-xac" in axial_args
    assert "-xal" in axial_args
    for bad_flag in ("-st", "-srt", "-stb", "-sic", "-sr"):
        assert bad_flag not in axial_args

    assert result.get("summary", {}).get("analysis_engine") == "depthmapxcli-axial"
    orientation = result.get("summary", {}).get("road_orientation_analysis") or {}
    assert orientation.get("dominant_orientation") == "东西向"


def test_road_orientation_analysis_is_length_weighted():
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[0.0, 0.0], [2.0, 0.0]]},
            "properties": {},
        },
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[0.0, 0.0], [0.0, 0.5]]},
            "properties": {},
        },
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[0.0, 0.0], [0.5, 0.5]]},
            "properties": {},
        },
    ]

    analysis = build_road_orientation_analysis(features)

    assert analysis["dominant_orientation"] == "东西向"
    assert analysis["secondary_orientation"] in {"南北向", "东北-西南向"}
    assert float(analysis["dominant_share"]) > 0.5


def test_axial_failure_raises_without_segment_fallback(monkeypatch):
    call_log = []
    _patch_core_runtime(monkeypatch, call_log, fail_axial=True)

    try:
        core.analyze_road_syntax(
            polygon=_sample_polygon(),
            coord_type="wgs84",
            mode="walking",
            graph_model="axial",
            highway_filter="all",
            include_geojson=True,
            radii_m=[600, 800],
            use_arcgis_webgl=False,
        )
    except RuntimeError as exc:
        assert "轴线图计算失败" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError for axial failure")

    modes = [entry["mode"] for entry in call_log]
    assert modes[:3] == ["IMPORT", "MAPCONVERT", "AXIAL"]
    assert "SEGMENT" not in modes
