from typing import List, Dict, Any
from django.contrib.gis.geos import (
    GEOSGeometry,    
)
import json
import requests

def fetch_layer_features_with_attributes(
        layer,
        minx: float,
        miny: float,
        maxx: float,
        maxy: float,
        limit: int = 2000,
        out_sr: int = 28356,
        use_cache: bool = True,
        preview_mode: bool = False
) -> List[Dict[str, Any]]:
    """
    Fetch features from ArcGIS REST service with maximum compatibility.
    Works with both modern and legacy servers including SCRC.
    """

    if not layer.server:
        logger.error(f"Layer {layer.name} has no server configured")
        return []

    # Adjust limit for preview mode
    if preview_mode:
        limit = min(limit, 500)

    base_url = layer.server.url.rstrip('/')
    layer_number = layer.number
    query_url = f"{base_url}/{layer_number}/query"

    # Determine server characteristics
    is_legacy = any(x in base_url.lower() for x in ['gislegacy', 'legacy', 'old'])
    is_scrc = 'scc.qld.gov.au' in base_url.lower()
    needs_ssl_bypass = is_legacy or is_scrc or 'https' in base_url

    # Create session
    session = create_session_with_retries()

    # Build headers
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Encoding': 'gzip, deflate',
        'Cache-Control': 'no-cache'
    }

    if is_scrc:
        headers['Referer'] = 'https://gislegacy.scc.qld.gov.au/'

    logger.info(f"Fetching features from: {query_url}")
    logger.info(f"Layer: {layer.name}, Bounds: ({minx},{miny}) to ({maxx},{maxy})")

    feature_results = []

    # SPECIAL HANDLING FOR SCRC - They don't support spatial queries
    if is_scrc or 'scc.qld.gov.au' in base_url.lower():
        logger.info("Using SCRC-specific query (no spatial filter)")

        params = {
            'f': 'json',
            'where': '1=1',
            'outFields': '*',
            'returnGeometry': 'true',
            'outSR': str(out_sr),
            'resultRecordCount': str(min(limit * 2, 2000))  # Get more, filter later
        }

        try:
            response = session.get(
                query_url,
                params=params,
                headers=headers,
                timeout=30,
                verify=False
            )

            if response.status_code == 200:
                data = response.json()

                if 'error' not in data:
                    features = data.get('features', [])

                    for feature in features:
                        try:
                            geom = parse_esri_geometry(feature.get('geometry'), srid=out_sr)

                            if geom and geom.valid:
                                # Filter by bounds client-side
                                if out_sr == 4326:
                                    # For WGS84, we can filter by bounds
                                    try:
                                        # Transform to WGS84 if needed for bounds check
                                        test_geom = geom if geom.srid == 4326 else geom.clone()
                                        if test_geom.srid != 4326:
                                            test_geom.transform(4326)

                                        bounds = test_geom.bounds
                                        # Check if geometry intersects with request bounds
                                        if (bounds[0] <= maxx and bounds[2] >= minx and
                                                bounds[1] <= maxy and bounds[3] >= miny):
                                            feature_results.append({
                                                'geometry': geom,
                                                'attributes': feature.get('attributes', {})
                                            })
                                    except:
                                        # If bounds check fails, include anyway
                                        feature_results.append({
                                            'geometry': geom,
                                            'attributes': feature.get('attributes', {})
                                        })
                                else:
                                    # For non-WGS84, include all (can't easily filter)
                                    feature_results.append({
                                        'geometry': geom,
                                        'attributes': feature.get('attributes', {})
                                    })

                                if len(feature_results) >= limit:
                                    break

                        except Exception as e:
                            logger.debug(f"Error processing SCRC feature: {e}")
                            continue

                    logger.info(f"SCRC query returned {len(feature_results)} features")
                    return feature_results[:limit]
                else:
                    logger.error(f"SCRC query error: {data['error']}")

        except Exception as e:
            logger.error(f"SCRC query failed: {e}")

    # STANDARD QUERY STRATEGIES FOR NON-SCRC SERVERS
    strategies = [
        {
            'name': 'ESRI JSON with envelope',
            'params': {
                'f': 'json',
                'where': '1=1',
                'geometry': f'{minx},{miny},{maxx},{maxy}',
                'geometryType': 'esriGeometryEnvelope',
                'spatialRel': 'esriSpatialRelIntersects',
                'inSR': '4326',
                'outSR': str(out_sr),
                'returnGeometry': 'true',
                'outFields': '*',
                'returnDistinctValues': 'false',
                'returnIdsOnly': 'false',
                'returnCountOnly': 'false',
                'maxRecordCount': str(limit),
                'resultRecordCount': str(limit)
            }
        },
        {
            'name': 'Simplified ESRI JSON',
            'params': {
                'f': 'json',
                'where': '1=1',
                'geometry': f'{minx},{miny},{maxx},{maxy}',
                'geometryType': 'esriGeometryEnvelope',
                'spatialRel': 'esriSpatialRelIntersects',
                'returnGeometry': 'true',
                'outFields': '*'
            }
        },
        {
            'name': 'GeoJSON format',
            'params': {
                'f': 'geojson',
                'where': '1=1',
                'geometry': f'{minx},{miny},{maxx},{maxy}',
                'geometryType': 'esriGeometryEnvelope',
                'spatialRel': 'esriSpatialRelIntersects',
                'inSR': 4326,
                'outSR': out_sr,
                'returnGeometry': 'true',
                'outFields': '*',
                'maxRecordCount': limit
            }
        },
        {
            'name': 'No spatial filter',
            'params': {
                'f': 'json',
                'where': '1=1',
                'returnGeometry': 'true',
                'outFields': '*',
                'outSR': str(out_sr),
                'resultRecordCount': str(min(100, limit))
            }
        }
    ]

    # Try each strategy
    for strategy in strategies:
        if feature_results:  # Already got results from SCRC handling
            break

        try:
            logger.debug(f"Trying strategy: {strategy['name']}")

            verify_ssl = not needs_ssl_bypass
            response = session.get(
                query_url,
                params=strategy['params'],
                headers=headers,
                timeout=15 if preview_mode else 30,
                verify=verify_ssl
            )

            if response.status_code != 200:
                logger.debug(f"HTTP {response.status_code} for {strategy['name']}")
                continue

            try:
                data = response.json()
            except json.JSONDecodeError:
                continue

            if 'error' in data:
                error_msg = data['error'].get('message', 'Unknown')
                logger.debug(f"Server error: {error_msg}")
                if 'does not exist' in error_msg.lower():
                    break  # Layer doesn't exist
                continue

            # Process features
            if strategy['params']['f'] == 'geojson':
                # GeoJSON format
                features = data.get('features', [])
                for feature in features[:limit]:
                    try:
                        geom_data = feature.get('geometry')
                        if geom_data:
                            geom = GEOSGeometry(json.dumps(geom_data), srid=out_sr)
                            if geom and geom.valid:
                                feature_results.append({
                                    'geometry': geom,
                                    'attributes': feature.get('properties', {})
                                })
                    except:
                        continue
            else:
                # ESRI JSON format
                features = data.get('features', [])
                for feature in features[:limit]:
                    try:
                        geom = parse_esri_geometry(
                            feature.get('geometry'),
                            srid=out_sr
                        )

                        if geom and geom.valid:
                            feature_results.append({
                                'geometry': geom,
                                'attributes': feature.get('attributes', {})
                            })
                    except:
                        continue

            if feature_results:
                logger.info(f"Got {len(feature_results)} features using {strategy['name']}")
                break

            if 'features' in data and isinstance(data['features'], list):
                logger.info(f"No features in area for {layer.name}")
                break

        except requests.exceptions.Timeout:
            if preview_mode:
                break
            continue
        except Exception as e:
            logger.debug(f"Strategy {strategy['name']} failed: {e}")
            continue

    if not feature_results:
        logger.warning(f"All strategies failed for {layer.name}")

    return feature_results[:limit]

