# Analysis Recipes

Read this file after discovering candidate domains and metric IDs from `metric-catalog-index.yaml`, and before querying detailed entries from `metric-catalog.yaml`. A recipe forms a candidate metric combination; it does not prove that a metric is implemented, available, comparable, or usable in the current run. Intersect the candidates with the current AnalysisRun first, then validate the remaining metric IDs against the detailed Catalog. Preserve contradictory evidence and every metric limitation.

## Community daily-life area

- Required families: population, POI, road syntax, nightlight.
- Candidate metrics: `population.total`, `poi.grid_density`, `poi.local_entropy`, `road.integration`, `nightlight.mean_radiance`.
- Support only a stable daily-life-area hypothesis when population and daily-service supply are both strong, POI mix is not single-category dominated, and the road/nightlight proxies do not contradict it.
- Do not convert population or POI density into purchasing power or observed visits.

## Office and business area

- Required families: POI, road syntax, nightlight or time-series evidence.
- Candidate metrics: `poi.lq`, `poi.category_density`, `road.integration`, `road.choice`, `nightlight.sector_profile`.
- Require an office-related category specialization plus independent access or temporal evidence.
- Treat company POIs as facilities, not employment counts.

## Night-time activity

- Required families: nightlight, POI, road syntax.
- Candidate metrics: `nightlight.p90`, `nightlight.hotspot_ratio`, `poi.lq`, `road.choice`.
- Use nightlight as an activity proxy and require relevant evening POI supply or route evidence before discussing a night-time activity cluster.
- Do not claim sales, footfall, or night-economy performance.

## Commercial supply gap

- Required families: target-category POI, population or activity proxy, road syntax.
- Candidate metrics: `poi.category_density`, `poi.lq`, `population.total`, `nightlight.mean_radiance`, `road.integration`.
- A low target-category supply value is only a candidate gap when an independent customer/activity proxy and access evidence are present.
- Search for a no-demand explanation and named competitors before recommending investment.

## Cultural destination

- Required families: cultural POI, access, road syntax, project documents or confirmed spatial assets.
- Candidate metrics: `poi.category_count`, `poi.lq`, `isochrone.reachable_area`, `road.integration`.
- Metrics can support surrounding cultural context and access, but a destination anchor also requires a confirmed asset, operating content, capacity, and an accountable operator.
- Do not treat a historic building or design intention as validated demand.
