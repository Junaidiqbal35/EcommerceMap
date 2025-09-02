# management/commands/validate_scrc_layers.py
# Create this file in your app's management/commands directory

from django.core.management.base import BaseCommand
from django.contrib.gis.geos import Point
from core.models import Layer, Server  # Replace with your app name
import requests
import json
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Validate and fix SCRC (and other) layer configurations'

    def add_arguments(self, parser):
        parser.add_argument(
            '--server',
            type=str,
            default='SCRC',
            help='Server name to validate (default: SCRC)',
        )
        parser.add_argument(
            '--fix',
            action='store_true',
            help='Actually fix the issues found',
        )
        parser.add_argument(
            '--test-download',
            action='store_true',
            help='Test downloading a sample of features',
        )

    def handle(self, *args, **options):
        server_name = options['server']
        fix_mode = options['fix']
        test_download = options['test_download']

        self.stdout.write(f"Validating layers for server: {server_name}")
        if not fix_mode:
            self.stdout.write(self.style.WARNING("Running in TEST mode. Use --fix to apply changes"))

        # Get all layers for the server
        layers = Layer.objects.filter(server__name__icontains=server_name).select_related('server')

        if not layers.exists():
            self.stdout.write(self.style.ERROR(f"No layers found for server {server_name}"))
            return

        self.stdout.write(f"Found {layers.count()} layers to validate")

        issues = {
            'no_server': [],
            'wrong_number': [],
            'no_geometry': [],
            'unreachable': [],
            'no_features': [],
            'fixed': []
        }

        for layer in layers:
            self.stdout.write(f"\nValidating: {layer.name} (ID: {layer.layer_id})")

            # Check 1: Has server?
            if not layer.server:
                issues['no_server'].append(layer)
                self.stdout.write(self.style.ERROR("  ✗ No server configured"))
                continue

            # Check 2: Has geometry for zoom?
            if not layer.geometry and not (layer.offsetX and layer.offsetY):
                issues['no_geometry'].append(layer)
                self.stdout.write(self.style.WARNING("  ⚠ No geometry for zoom"))

                if fix_mode and layer.server:
                    # Fix by using server extent center
                    if (layer.server.extent_min_x is not None and
                            layer.server.extent_max_x is not None):
                        cx = (layer.server.extent_min_x + layer.server.extent_max_x) / 2
                        cy = (layer.server.extent_min_y + layer.server.extent_max_y) / 2

                        if -180 <= cx <= 180 and -90 <= cy <= 90:
                            layer.geometry = Point(cx, cy, srid=4326)
                            layer.save()
                            self.stdout.write(self.style.SUCCESS(f"    ✓ Fixed geometry"))
                            issues['fixed'].append(('geometry', layer))

            # Check 3: Validate layer number
            base_url = layer.server.url.rstrip('/')
            correct_number = self.detect_correct_layer_number(base_url, layer.name, layer.number)

            if correct_number is None:
                issues['unreachable'].append(layer)
                self.stdout.write(self.style.ERROR(f"  ✗ Cannot reach layer at {base_url}/{layer.number}"))
            elif correct_number != layer.number:
                issues['wrong_number'].append(layer)
                self.stdout.write(self.style.WARNING(
                    f"  ⚠ Wrong layer number: {layer.number} should be {correct_number}"
                ))

                if fix_mode:
                    old_number = layer.number
                    layer.number = correct_number
                    layer.save()
                    self.stdout.write(self.style.SUCCESS(
                        f"    ✓ Fixed layer number: {old_number} -> {correct_number}"
                    ))
                    issues['fixed'].append(('number', layer))
            else:
                self.stdout.write(self.style.SUCCESS(f"  ✓ Layer number correct: {layer.number}"))

            # Check 4: Test feature retrieval
            if test_download and correct_number is not None:
                feature_count = self.test_feature_retrieval(base_url, correct_number or layer.number)
                if feature_count == 0:
                    issues['no_features'].append(layer)
                    self.stdout.write(self.style.WARNING(f"  ⚠ No features found in test area"))
                elif feature_count > 0:
                    self.stdout.write(self.style.SUCCESS(f"  ✓ Found {feature_count} features"))

        # Summary
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write(self.style.SUCCESS(f"\nValidation Summary for {server_name}:"))
        self.stdout.write(f"Total layers checked: {layers.count()}")
        self.stdout.write(f"No server configured: {len(issues['no_server'])}")
        self.stdout.write(f"Wrong layer number: {len(issues['wrong_number'])}")
        self.stdout.write(f"No geometry: {len(issues['no_geometry'])}")
        self.stdout.write(f"Unreachable: {len(issues['unreachable'])}")

        if test_download:
            self.stdout.write(f"No features in test: {len(issues['no_features'])}")

        if fix_mode:
            self.stdout.write(self.style.SUCCESS(f"Fixed issues: {len(issues['fixed'])}"))
            for fix_type, layer in issues['fixed']:
                self.stdout.write(f"  - Fixed {fix_type} for {layer.name}")

        # List problematic layers
        if issues['unreachable']:
            self.stdout.write(self.style.ERROR("\nUnreachable layers:"))
            for layer in issues['unreachable'][:10]:  # Show first 10
                self.stdout.write(f"  - {layer.name} (ID: {layer.layer_id})")

    def detect_correct_layer_number(self, base_url, layer_name, current_number):
        """Try to find the correct layer number"""

        # First try the current number
        test_url = f"{base_url}/{current_number}"
        try:
            response = requests.get(f"{test_url}?f=json", timeout=5)
            if response.status_code == 200:
                data = response.json()
                if 'error' not in data:
                    # Verify it's the right layer by name
                    svc_name = data.get('name', '').lower()
                    if layer_name.lower() in svc_name or svc_name in layer_name.lower():
                        return current_number
        except:
            pass

        # Try to get service catalog
        try:
            service_root = '/'.join(
                base_url.split('/')[:-1]) if '/MapServer' in base_url or '/FeatureServer' in base_url else base_url
            response = requests.get(f"{service_root}?f=json", timeout=5)
            if response.status_code == 200:
                data = response.json()
                layers = data.get('layers', [])

                # Look for exact match
                for svc_layer in layers:
                    if svc_layer.get('name', '').lower() == layer_name.lower():
                        return svc_layer.get('id')

                # Look for partial match
                for svc_layer in layers:
                    svc_name = svc_layer.get('name', '').lower()
                    if layer_name.lower() in svc_name or svc_name in layer_name.lower():
                        return svc_layer.get('id')
        except Exception as e:
            logger.debug(f"Error checking service catalog: {e}")

        return None

    def test_feature_retrieval(self, base_url, layer_number):
        """Test if we can retrieve features"""

        # Use a test area (Sunshine Coast area)
        test_bounds = {
            'minx': 152.9,
            'miny': -26.7,
            'maxx': 153.1,
            'maxy': -26.5
        }

        url = f"{base_url}/{layer_number}/query"
        params = {
            'f': 'json',
            'where': '1=1',
            'geometry': f"{test_bounds['minx']},{test_bounds['miny']},{test_bounds['maxx']},{test_bounds['maxy']}",
            'geometryType': 'esriGeometryEnvelope',
            'spatialRel': 'esriSpatialRelIntersects',
            'inSR': 4326,
            'outSR': 4326,
            'returnCountOnly': 'true'
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if 'error' not in data:
                    return data.get('count', 0)
        except:
            pass

        return -1  # Error indicator