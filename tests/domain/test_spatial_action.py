from shapely.geometry import Polygon, mapping

from modules.spatial_action import LocalizedPatternInputCell, SpatialActionService


def _square(x, y, size=0.001):
    return mapping(
        Polygon(
            [
                (x, y),
                (x + size, y),
                (x + size, y + size),
                (x, y + size),
                (x, y),
            ]
        )
    )


def test_local_patterns_group_significant_neighbors_and_keep_singleton_outlier():
    cells = [
        LocalizedPatternInputCell(cell_id="a", metric_id="spatial.gi_star", value=10, geometry=_square(0, 0), p_value=0.001, z_score=3, cluster_type="hotspot", neighbor_ids=["b"]),
        LocalizedPatternInputCell(cell_id="b", metric_id="spatial.gi_star", value=11, geometry=_square(0.001, 0), p_value=0.002, z_score=3.2, cluster_type="hotspot", neighbor_ids=["a"]),
        LocalizedPatternInputCell(cell_id="c", metric_id="spatial.gi_star", value=1, geometry=_square(0.01, 0), p_value=0.003, z_score=-3, cluster_type="coldspot"),
        LocalizedPatternInputCell(cell_id="d", metric_id="spatial.gi_star", value=4, geometry=_square(0.02, 0), p_value=0.8, z_score=0.1),
    ]
    result = SpatialActionService().analyze_local_patterns(cells)
    assert result.evidence_state == "measured"
    assert {zone.pattern_type for zone in result.zones} == {"hotspot", "local_outlier"}
    assert all(cell.adjusted_p_value is not None for cell in result.cells)


def test_local_patterns_without_p_values_are_proxy_not_hotspot():
    result = SpatialActionService().analyze_local_patterns(
        [
            LocalizedPatternInputCell(
                cell_id=str(index),
                metric_id="poi.grid_density",
                value=value,
                geometry=_square(index * 0.002, 0),
            )
            for index, value in enumerate([1, 2, 3, 10])
        ]
    )
    assert result.evidence_state == "proxy"
    assert result.pattern_label == "高值集中区"
    assert "p_values_missing_not_statistical_hotspot" in result.diagnostics
