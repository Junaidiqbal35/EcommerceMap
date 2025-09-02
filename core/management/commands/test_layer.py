import sys
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Test layer functionality'

    def handle(self, *args, **options):
        test_layers()


def test_layers():
    """Test layer preview and export functionality"""
    from core.models import Layer, Server  # Replace with your app
    from core.views import (
        fetch_layer_features_with_attributes,
        test_layer_connection
    )
    import json

    print("=" * 60)
    print("LAYER FUNCTIONALITY TEST")
    print("=" * 60)

    # Test configuration
    test_areas = {
        'Brisbane': {'minx': 153.0, 'miny': -27.5, 'maxx': 153.05, 'maxy': -27.45},
        'Sunshine Coast': {'minx': 152.9, 'miny': -26.7, 'maxx': 153.1, 'maxy': -26.5},
        'Sydney': {'minx': 151.0, 'miny': -33.9, 'maxx': 151.1, 'maxy': -33.8},
    }

    results = {
        'total': 0,
        'working': [],
        'partial': [],
        'failed': []
    }

    # Get sample layers from each server
    servers = Server.objects.all()

    for server in servers:
        print(f"\nTesting server: {server.name}")
        print(f"URL: {server.url}")

        # Get first 2 layers from this server
        layers = Layer.objects.filter(server=server)[:2]

        for layer in layers:
            results['total'] += 1
            print(f"\n  Testing layer: {layer.name} (ID: {layer.layer_id})")

            # Test 1: Connection test
            conn_result = test_layer_connection(layer)

            if conn_result.get('accessible'):
                print(f"    ✓ Connection: SUCCESS")
                print(f"      - Geometry Type: {conn_result.get('geometryType')}")
                print(f"      - Max Records: {conn_result.get('maxRecordCount')}")
            else:
                print(f"    ✗ Connection: FAILED - {conn_result.get('error')}")
                results['failed'].append({
                    'layer': f"{layer.name} ({server.name})",
                    'error': conn_result.get('error')
                })
                continue

            # Test 2: Feature fetch test
            feature_test_passed = False
            for area_name, bounds in test_areas.items():
                try:
                    features = fetch_layer_features_with_attributes(
                        layer,
                        bounds['minx'],
                        bounds['miny'],
                        bounds['maxx'],
                        bounds['maxy'],
                        limit=10,
                        out_sr=4326
                    )

                    if features:
                        print(f"    ✓ Features ({area_name}): {len(features)} found")

                        # Show sample attributes
                        if features:
                            sample = features[0]
                            attrs = sample.get('attributes', {})
                            if attrs:
                                print(f"      - Sample attributes: {list(attrs.keys())[:5]}")

                        results['working'].append({
                            'layer': f"{layer.name} ({server.name})",
                            'features': len(features),
                            'area': area_name
                        })
                        feature_test_passed = True
                        break

                except Exception as e:
                    print(f"    ⚠ Features ({area_name}): Error - {str(e)[:50]}")

            if not feature_test_passed:
                print(f"    ⚠ No features found in any test area")
                results['partial'].append({
                    'layer': f"{layer.name} ({server.name})",
                    'issue': 'No features in test areas'
                })

            # Test 3: Geometry/zoom capability
            if layer.geometry:
                print(f"    ✓ Geometry: Available for zoom")
            elif layer.offsetX and layer.offsetY:
                print(f"    ⚠ Geometry: Using offsets ({layer.offsetX}, {layer.offsetY})")
            else:
                print(f"    ✗ Geometry: Not available for zoom")

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Total layers tested: {results['total']}")
    print(f"✓ Fully working: {len(results['working'])}")
    print(f"⚠ Partially working: {len(results['partial'])}")
    print(f"✗ Failed: {len(results['failed'])}")

    if results['working']:
        print("\nWorking layers:")
        for item in results['working'][:5]:
            print(f"  - {item['layer']}: {item['features']} features in {item['area']}")

    if results['failed']:
        print("\nFailed layers:")
        for item in results['failed'][:5]:
            print(f"  - {item['layer']}: {item['error'][:50]}")

    # Recommendations
    if results['failed'] or results['partial']:
        print("\n" + "=" * 60)
        print("RECOMMENDATIONS")
        print("=" * 60)

        errors = [item.get('error', '') for item in results['failed']]

        if any('SSL' in str(e) for e in errors):
            print("• SSL issues detected - verify=False is needed for some servers")

        if any('does not exist' in str(e) for e in errors):
            print("• Some layer numbers appear to be incorrect")
            print("  Run: python manage.py auto_fix_layers")

        if results['partial']:
            print("• Some layers have no features in test areas")
            print("  - Try different geographic areas")
            print("  - Check if layers have any data")

        print("\nTo fix issues automatically:")
        print("1. python manage.py fix_layer_geometry")
        print("2. python manage.py auto_fix_layers")
        print("3. python manage.py diagnose_layers --verbose")
    else:
        print("\n✅ All tested layers are working correctly!")

    return results


if __name__ == '__main__':
    # Can be run directly or as management command
    test_layers()