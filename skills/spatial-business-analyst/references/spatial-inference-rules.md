# Spatial inference rules

Use this reference for local hotspots, directions, entrances, roads, routes, and spatial-program actions.

## Move from global pattern to local object

A global total, average, or Moran's I may establish that a pattern exists, but it cannot locate an entrance, program, interface, or route. Continue to a localizable object when the decision is spatial:

- direction: sector or distance band;
- concentration: grid cell plus hotspot zone;
- access: entrance plus snapped road segment;
- movement: route plus matched road segments and break points;
- program allocation: hotspot zone, public space, street segment, or boundary interface.

Preserve object IDs and geometries in EvidenceSnapshot entries and artifacts.

## Hotspots and local clusters

- Use `alpha=0.05` unless the plan states otherwise.
- Apply Benjamini–Hochberg FDR for multiple cells by default.
- Merge adjacent significant cells only when cluster types agree.
- Keep a single significant cell as `local_outlier`; do not call it a continuous hotspot.
- Complete p-values and cluster classes can support `measured` local-statistical evidence.
- Quantiles, high values, or z-scores without significance produce a “high-value concentration area” with `proxy` state, not a statistical hotspot.

Global Moran's I answers whether the full distribution is spatially autocorrelated. It cannot locate project actions. If the decision concerns an entrance or program location, continue to Gi*, LISA, and the relevant entrance or route relationship.

## Direction and distance

Compare normalized rates, densities, shares, or accessible exposure. Raw directional counts are descriptive only when sector area, reachable area, distance opportunity, or network exposure differs. Keep the project origin and coordinate system explicit.

## Entrance semantics

An entrance is a physical project-to-network access anchor, not a generic analysis origin.

- `existing_observed`: documented or observed entrance.
- `project_planned`: explicit design entrance.
- `inferred_candidate`: project-boundary × walkable-road intersection; always `experimental_assumption`.

A selected map center, POI centroid, isochrone boundary, or area-sampling seed is not automatically an entrance. If the run lacks a project boundary or explicit entrance and the question does not require entrance choice, exclude entrance metrics as not applicable.

Compare entrances through planned primary, supporting, and diagnostic metrics; do not hide unlike measures in an unexplained weighted score.

## Routes

Route only entrance–destination pairs resolved from locked evidence capabilities. Valhalla supplies real walking geometry, distance, and duration. Do not replace a blocked route with a straight line or circular buffer. Straight-line distance is only the denominator for detour ratio.

If depthmapX is unavailable, preserve successful route distance and duration while marking syntax-overlap metrics blocked. Match route geometry to road segments before calculating integration or choice overlap.

## Translating evidence into action

A spatial finding is complete only when it identifies:

1. the local object;
2. the observed or proxy pattern;
3. the mechanism being tested;
4. the project object that can change;
5. the action or prototype;
6. the assumption and disconfirming observation.
