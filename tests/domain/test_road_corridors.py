from __future__ import annotations

from modules.road.corridors import build_road_corridors


def _edge(edge_id, left, right, nain):
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [left, right]},
        "properties": {
            "edge_id": edge_id,
            "from_node": f"node:{left}",
            "to_node": f"node:{right}",
            "road_name": "测试路",
            "length_m": 100,
            "nain_global": nain,
        },
    }


def test_corridors_are_topologically_continuous_components():
    edges = [
        _edge("a", [0, 0], [1, 0], 10),
        _edge("b", [1, 0], [2, 0], 9),
        _edge("c", [10, 0], [11, 0], 8),
        _edge("d", [20, 0], [21, 0], 1),
    ]

    collection, summary = build_road_corridors(edges, quantile=0.5, minimum_edge_count=2)

    assert summary["corridor_count"] == 1
    corridor = collection["features"][0]["properties"]
    assert corridor["metric"] == "nain"
    assert corridor["member_edge_ids"] == ["a", "b"]
    assert corridor["edge_count"] == 2
    assert corridor["length_m"] == 200


def test_corridor_builder_does_not_merge_geometric_crossings_without_shared_nodes():
    edges = [
        _edge("horizontal-a", [0, 1], [1, 1], 10),
        _edge("horizontal-b", [1, 1], [2, 1], 10),
        _edge("vertical-a", [1, 0], [1, 1], 10),
        _edge("vertical-b", [1, 1], [1, 2], 10),
    ]
    for index, feature in enumerate(edges):
        feature["properties"]["from_node"] = f"network-{index}:left"
        feature["properties"]["to_node"] = f"network-{index}:right"

    collection, _ = build_road_corridors(edges, quantile=0, minimum_edge_count=2)

    assert collection["count"] == 0
