# Area Heatmap Basemap Projection Debug Report

Status: DONE

Symptom: Adding the static basemap to the POI iteration area heatmap made the map appear misaligned or visually stretched, while the SVG without basemap looked acceptable.

Root cause: The backend generated heatmap points, cells, and boundaries in a fixed 100x100 coordinate space, while the frontend also forced the SVG into a fixed 100x100 viewBox and 640/420 aspect ratio. The static map image was then inserted into that old frame, so the basemap and overlays did not share one Web Mercator viewport.

Fix: The backend now derives one shared Web Mercator viewport from the analysis polygon, emits dynamic view/viewBox/aspect/viewport metadata, builds the static map size from the real projected aspect ratio, and projects boundary, cells, and POI points through the same viewport. The frontend reads those metadata fields for SVG viewBox, image width/height, and aspect-ratio, and displays the basemap image again without cover/slice behavior.

Evidence: `python -m py_compile modules\agent\poi_iteration_build_service.py`, `npm.cmd test -- frontend/tests/agent-sessions.test.js`, and `npm.cmd run build` all passed.

Regression test: `frontend/tests/agent-sessions.test.js` now asserts dynamic area heatmap viewBox, view size, and aspect-ratio helper output.
