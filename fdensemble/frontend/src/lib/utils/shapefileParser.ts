// shpjs is imported lazily inside parseAndValidateShapefile to avoid loading
// Node's `buffer` polyfill at page startup (causes a TypeError in some browsers).

export interface ValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
  districtCount: number;
  bounds: [number, number, number, number];
  geometryType: string;
}

export interface ParseResult {
  geojson: GeoJSON.FeatureCollection;
  validation: ValidationResult;
}

export function validateGeoJSON(geojson: GeoJSON.FeatureCollection): ValidationResult {
  const validation: ValidationResult = {
    valid: false,
    errors: [],
    warnings: [],
    districtCount: 0,
    bounds: [0, 0, 0, 0],
    geometryType: '',
  };

  const features = geojson.features;
  validation.districtCount = features.length;

  if (features.length === 0) {
    validation.errors.push('GeoJSON contains no features.');
    return validation;
  }

  const nullCount = features.filter(f => !f.geometry).length;
  if (nullCount > 0) {
    validation.errors.push(`${nullCount} feature(s) have null geometry.`);
  }

  const geomTypes = new Set(
    features.filter(f => f.geometry).map(f => f.geometry!.type)
  );
  const allowedTypes = new Set(['Polygon', 'MultiPolygon']);
  const badTypes = [...geomTypes].filter(t => !allowedTypes.has(t));
  if (badTypes.length > 0) {
    validation.errors.push(
      `Unexpected geometry type(s): ${badTypes.join(', ')}. Expected Polygon or MultiPolygon.`
    );
  }
  validation.geometryType = [...geomTypes].join(', ') || 'unknown';

  try {
    const lons: number[] = [];
    const lats: number[] = [];
    features.forEach(f => {
      if (!f.geometry) return;
      extractCoords(f.geometry as GeoJSON.Geometry, lons, lats);
    });
    if (lons.length > 0) {
      validation.bounds = [
        Math.min(...lons),
        Math.min(...lats),
        Math.max(...lons),
        Math.max(...lats),
      ];
      if (Math.max(...lons) > 180 || Math.min(...lons) < -180) {
        validation.warnings.push(
          'Coordinates appear to be in a projected CRS (not WGS84 / EPSG:4326). ' +
          'Maps may not render correctly.'
        );
      }
    }
  } catch {
    validation.warnings.push('Could not compute bounding box.');
  }

  validation.valid = validation.errors.length === 0;
  return validation;
}

export async function parseAndValidateShapefile(file: File): Promise<ParseResult> {
  const earlyValidation: ValidationResult = {
    valid: false,
    errors: [],
    warnings: [],
    districtCount: 0,
    bounds: [0, 0, 0, 0],
    geometryType: '',
  };

  if (!file.name.toLowerCase().endsWith('.zip')) {
    earlyValidation.errors.push('Please upload a .zip file containing .shp, .dbf, and .shx files.');
    return { geojson: emptyFC(), validation: earlyValidation };
  }

  let geojson: GeoJSON.FeatureCollection;
  try {
    // Polyfill Buffer globally if needed (shpjs's browser build uses it).
    // Done lazily so it doesn't affect page startup time.
    if (typeof (globalThis as any).Buffer === 'undefined') {
      const { Buffer: Buf } = await import('buffer');
      (globalThis as any).Buffer = Buf;
    }
    const { default: shp } = await import('shpjs');
    const buffer = await file.arrayBuffer();
    const result = await shp(buffer as ArrayBuffer);
    geojson = Array.isArray(result) ? result[0] : result;
  } catch (err) {
    earlyValidation.errors.push(
      `Failed to parse shapefile: ${err instanceof Error ? err.message : String(err)}`
    );
    return { geojson: emptyFC(), validation: earlyValidation };
  }

  return { geojson, validation: validateGeoJSON(geojson) };
}

function extractCoords(geom: GeoJSON.Geometry, lons: number[], lats: number[]) {
  if (geom.type === 'Polygon') {
    for (const [lon, lat] of geom.coordinates[0]) {
      lons.push(lon);
      lats.push(lat);
    }
  } else if (geom.type === 'MultiPolygon') {
    for (const poly of geom.coordinates) {
      for (const [lon, lat] of poly[0]) {
        lons.push(lon);
        lats.push(lat);
      }
    }
  }
}

function emptyFC(): GeoJSON.FeatureCollection {
  return { type: 'FeatureCollection', features: [] };
}
