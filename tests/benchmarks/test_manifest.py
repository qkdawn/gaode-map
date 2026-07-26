from pathlib import Path

import yaml


MANIFEST = Path(__file__).with_name("spatial_business_analyst.yaml")
REQUIRED = {"id", "class", "scenario", "goal", "prompt", "must", "must_not"}


def test_spatial_business_benchmark_manifest_is_well_formed():
    payload = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assert payload["schema"] == "spatial-business-analyst-benchmark/v1"
    cases = payload["cases"]
    assert len(cases) == 9
    assert {case["class"] for case in cases} == {"forward", "adversarial"}
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))
    for case in cases:
        assert REQUIRED <= case.keys()
        assert case["prompt"]
        assert case["must"]
        assert case["must_not"]
