function buildPoiRuntimePoints(pois, options = {}) {
    const list = Array.isArray(pois) ? pois : [];
    const defaultTypeId = String(options.defaultTypeId || 'default');
    const normalizeLngLat = typeof options.normalizeLngLat === 'function'
        ? options.normalizeLngLat
        : () => null;
    const resolveTypeId = typeof options.resolveTypeId === 'function'
        ? options.resolveTypeId
        : () => '';
    const summarizeCoordInput = typeof options.summarizeCoordInput === 'function'
        ? options.summarizeCoordInput
        : (value) => value;
    let invalidPointCount = 0;
    const invalidPointSamples = [];
    const points = list.map((poi, idx) => {
        const loc = normalizeLngLat(poi && poi.location, 'poi.runtime.location');
        if (!loc) {
            invalidPointCount += 1;
            if (invalidPointSamples.length < 5) {
                invalidPointSamples.push({
                    idx,
                    id: (poi && (poi.poi_id || poi.id)) || '',
                    name: (poi && poi.name) || '',
                    location: summarizeCoordInput(poi && poi.location),
                });
            }
            return null;
        }
        const matchedType = resolveTypeId(poi && (poi.typecode || poi.type)) || defaultTypeId;
        return {
            lng: Number(loc[0]),
            lat: Number(loc[1]),
            name: poi && poi.name ? poi.name : '',
            type: matchedType,
            address: poi && poi.address ? poi.address : '',
            lines: poi && Array.isArray(poi.lines) ? poi.lines : [],
            _pid: (poi && (poi.poi_id || poi.id)) || `p-${idx}`,
        };
    }).filter((poi) => !!poi);

    return { points, invalidPointCount, invalidPointSamples };
}

export { buildPoiRuntimePoints };
