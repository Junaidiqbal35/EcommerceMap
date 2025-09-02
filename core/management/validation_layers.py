def validate_implementation():
    """Complete validation of layer preview and export functionality"""

    print("=" * 70)
    print("LAYER SYSTEM VALIDATION")
    print("=" * 70)

    from django.conf import settings
    from core.models import Layer, Server  # Replace with your app
    from core.views import (
        fetch_layer_features_with_attributes,
        test_layer_connection,
        parse_esri_geometry
    )
    import requests
    import json

    results = {
        'total_servers': 0,
        'total_layers': 0,
        'working_servers': [],
        'failed_servers': [],
        'working_layers': [],
        'failed_layers': [],
        'preview_ready': [],
        'export_ready': [],
        'issues': []
    }

    # Test 1: Check if imports work
    print("\n1. Testing imports...")
    try:
        import urllib3
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        from django.contrib.gis.geos import Point, LineString, Polygon
        print("   ✓ All required imports available")
    except ImportError as e:
        print(f"   ✗ Missing import: {e}")
        results['issues'].append(f"Missing import: {e}")

    # Test 2: Check SSL handling
    print("\n2. Testing SSL handling...")
    try:
        # Test a known SSL-problematic server
        test_url = "https://gislegacy.scc.qld.gov.au/arcgis/rest/services"
        response = requests.get(test_url, verify=False, timeout=5)
        if response.status_code in [200, 403, 404]:  # Any response means connection worked
            print("   ✓ SSL bypass working")
        else:
            print(f"   ⚠ SSL test returned status {response.status_code}")
    except Exception as e:
        print(f"   ⚠ SSL test error: {e}")
        results['issues'].append("SSL bypass may not be working")

    # Test 3: Validate each server
    print("\n3. Testing servers...")
    servers = Server.objects.all()
    results['total_servers'] = servers.count()

    for server in servers:
        print(f"\n   Testing: {server.name}")
        print(f"   URL: {server.url}")

        try:
            # Check if server is accessible
            test_url = f"{server.url}?f=json"
            response = requests.get(
                test_url,
                timeout=5,
                verify=False,
                headers={'User-Agent': 'Mozilla/5.0'}
            )

            if response.status_code == 200:
                data = response.json()
                if 'error' not in data:
                    layer_count = len(data.get('layers', []))
                    print(f"   ✓ Server OK - {layer_count} layers available")
                    results['working_servers'].append(server.name)
                else:
                    print(f"   ✗ Server error: {data['error'].get('message')}")
                    results['failed_servers'].append(server.name)
            else:
                print(f"   ✗ HTTP {response.status_code}")
                results['failed_servers'].append(server.name)

        except Exception as e:
            print(f"   ✗ Connection failed: {str(e)[:50]}")
            results['failed_servers'].append(server.name)

    # Test 4: Sample layers from each server
    print("\n4. Testing layer functionality...")

    test_bounds = {
        'minx': 153.0,
        'miny': -27.5,
        'maxx': 153.05,
        'maxy': -27.45
    }

    for server in servers[:5]:  # Test first 5 servers
        layers = Layer.objects.filter(server=server)[:2]  # 2 layers per server

        for layer in layers:
            results['total_layers'] += 1
            print(f"\n   Layer: {layer.name} (ID: {layer.layer_id})")

            # Test connection
            conn_result = test_layer_connection(layer)

            if conn_result.get('accessible'):
                print(f"   ✓ Connection OK")
                results['working_layers'].append(layer.layer_id)

                # Test feature fetch
                try:
                    features = fetch_layer_features_with_attributes(
                        layer,
                        test_bounds['minx'],
                        test_bounds['miny'],
                        test_bounds['maxx'],
                        test_bounds['maxy'],
                        limit=5,
                        out_sr=4326,
                        preview_mode=True
                    )

                    if features:
                        print(f"   ✓ Preview ready - {len(features)} features")
                        results['preview_ready'].append(layer.layer_id)

                        # Test geometry parsing
                        valid_geoms = sum(1 for f in features if f.get('geometry') and f['geometry'].valid)
                        print(f"   ✓ Geometry parsing - {valid_geoms}/{len(features)} valid")

                        if valid_geoms == len(features):
                            results['export_ready'].append(layer.layer_id)
                    else:
                        print(f"   ⚠ No features in test area")

                except Exception as e:
                    print(f"   ✗ Fetch error: {str(e)[:50]}")

            else:
                print(f"   ✗ Not accessible: {conn_result.get('error')}")
                results['failed_layers'].append(layer.layer_id)

    # Test 5: ESRI geometry parsing
    print("\n5. Testing ESRI geometry parser...")
    test_geometries = [
        {'x': 153.0, 'y': -27.5},  # Point
        {'paths': [[[153, -27], [153.1, -27.1]]]},  # Polyline
        {'rings': [[[153, -27], [153.1, -27], [153.1, -27.1], [153, -27.1], [153, -27]]]},  # Polygon
    ]

    for i, geom_dict in enumerate(test_geometries):
        try:
            geom = parse_esri_geometry(geom_dict)
            if geom and geom.valid:
                print(f"   ✓ Geometry type {i + 1}: {geom.geom_type}")
            else:
                print(f"   ✗ Geometry type {i + 1} failed")
                results['issues'].append(f"ESRI geometry parsing failed for type {i + 1}")
        except Exception as e:
            print(f"   ✗ Geometry type {i + 1} error: {e}")
            results['issues'].append(f"ESRI parser error: {e}")

    # Test 6: Check cache
    print("\n6. Testing cache...")
    try:
        from django.core.cache import cache
        cache.set('test_key', 'test_value', 60)
        if cache.get('test_key') == 'test_value':
            print("   ✓ Cache working")
        else:
            print("   ⚠ Cache not working properly")
            results['issues'].append("Cache not configured")
    except Exception as e:
        print(f"   ⚠ Cache error: {e}")
        results['issues'].append("Cache error")

    # Final Summary
    print("\n" + "=" * 70)
    print("VALIDATION SUMMARY")
    print("=" * 70)

    print(f"\nServers:")
    print(f"  Total: {results['total_servers']}")
    print(f"  Working: {len(results['working_servers'])} ({', '.join(results['working_servers'][:3])}...)")
    print(f"  Failed: {len(results['failed_servers'])}")

    print(f"\nLayers Tested:")
    print(f"  Total: {results['total_layers']}")
    print(f"  Working: {len(results['working_layers'])}")
    print(f"  Preview Ready: {len(results['preview_ready'])}")
    print(f"  Export Ready: {len(results['export_ready'])}")
    print(f"  Failed: {len(results['failed_layers'])}")

    if results['working_layers']:
        success_rate = len(results['working_layers']) / results['total_layers'] * 100
        print(f"\n✓ Success Rate: {success_rate:.1f}%")

    if results['issues']:
        print(f"\n⚠ Issues Found:")
        for issue in results['issues']:
            print(f"  - {issue}")

    # Recommendations
    print("\n" + "=" * 70)
    print("RECOMMENDATIONS")
    print("=" * 70)

    if len(results['failed_servers']) > 0:
        print("\n1. Some servers are not accessible:")
        print("   - Check server URLs are correct")
        print("   - Verify network connectivity")
        print("   - Some servers may require authentication")

    if len(results['preview_ready']) < len(results['working_layers']):
        print("\n2. Some layers have no features in test area:")
        print("   - Try different geographic areas")
        print("   - Check if layers have any data")
        print("   - Verify spatial reference systems")

    if not results['export_ready']:
        print("\n3. Export functionality needs attention:")
        print("   - Check geometry parsing")
        print("   - Verify DXF generation code")

    if results['success_rate'] < 80:
        print("\n4. Success rate is below 80%:")
        print("   - Run: python manage.py auto_fix_layers")
        print("   - Check layer numbers match server")
        print("   - Some layers may be deprecated")
    else:
        print("\n✅ System is working well! Most layers are functional.")

    print("\n" + "=" * 70)
    print("QUICK TEST URLS")
    print("=" * 70)

    if results['working_layers']:
        layer_id = results['working_layers'][0]
        print(f"\nTest these in your browser:")
        print(f"1. Layer status: /layer-preview-status/?layer_id={layer_id}")
        print(f"2. Layer test: /test-layer/{layer_id}/")
        print(
            f"3. Full preview: /layer-preview-features/?layer_id={layer_id}&minx=153&miny=-27.5&maxx=153.05&maxy=-27.45")

    return results


# Run validation
if __name__ == '__main__':
    results = validate_implementation()

    # Return exit code based on success
    import sys

    if results.get('success_rate', 0) >= 80:
        sys.exit(0)  # Success
    else:
        sys.exit(1)  # Needs