from django.core.management.base import BaseCommand
from django.contrib.gis.geos import Point
from core.models import Layer, Server  # Replace with your app name
import requests
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Automatically fix common layer configuration issues'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be fixed without making changes',
        )
        parser.add_argument(
            '--server',
            type=str,
            help='Fix only layers from specific server',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        server_filter = options['server']

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made"))

        # Get layers to fix
        layers = Layer.objects.select_related('server').all()
        if server_filter:
            layers = layers.filter(server__name__icontains=server_filter)

        self.stdout.write(f"Checking {layers.count()} layers...")

        fixes = {
            'geometry_fixed': 0,
            'number_fixed': 0,
            'url_fixed': 0,
            'total_fixed': 0
        }

        for layer in layers:
            layer_fixed = False

            # Fix 1: Missing geometry
            if not layer.geometry:
                if layer.offsetX and layer.offsetY:
                    if -180 <= layer.offsetX <= 180 and -90 <= layer.offsetY <= 90:
                        if not dry_run:
                            layer.geometry = Point(layer.offsetX, layer.offsetY, srid=4326)
                        fixes['geometry_fixed'] += 1
                        layer_fixed = True
                        self.stdout.write(f"  ✓ Fixed geometry for {layer.name} using offsets")
                elif layer.server and layer.server.extent_min_x:
                    cx = (layer.server.extent_min_x + layer.server.extent_max_x) / 2
                    cy = (layer.server.extent_min_y + layer.server.extent_max_y) / 2
                    if -180 <= cx <= 180 and -90 <= cy <= 90:
                        if not dry_run:
                            layer.geometry = Point(cx, cy, srid=4326)
                        fixes['geometry_fixed'] += 1
                        layer_fixed = True
                        self.stdout.write(f"  ✓ Fixed geometry for {layer.name} using server extent")

            # Fix 2: Wrong layer number
            if layer.server:
                correct_number = self.find_correct_layer_number(
                    layer.server.url,
                    layer.name,
                    layer.number
                )

                if correct_number is not None and correct_number != layer.number:
                    if not dry_run:
                        old_number = layer.number
                        layer.number = correct_number
                    fixes['number_fixed'] += 1
                    layer_fixed = True
                    self.stdout.write(
                        f"  ✓ Fixed layer number for {layer.name}: "
                        f"{layer.number} -> {correct_number}"
                    )

            # Save changes
            if layer_fixed and not dry_run:
                layer.save()
                fixes['total_fixed'] += 1

        # Summary
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write(self.style.SUCCESS("Auto-Fix Summary:"))
        self.stdout.write(f"Geometry fixed: {fixes['geometry_fixed']}")
        self.stdout.write(f"Layer numbers fixed: {fixes['number_fixed']}")

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(
                f"Total layers fixed: {fixes['total_fixed']}"
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f"Would fix {fixes['geometry_fixed'] + fixes['number_fixed']} issues"
            ))
            self.stdout.write("Run without --dry-run to apply fixes")

    def find_correct_layer_number(self, server_url, layer_name, current_number):
        """Find the correct layer number by querying the service"""
        if not server_url:
            return None

        base_url = server_url.rstrip('/')

        # First check if current number is valid
        try:
            response = requests.get(
                f"{base_url}/{current_number}?f=json",
                timeout=3,
                verify=False,
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            if response.status_code == 200:
                data = response.json()
                if 'error' not in data:
                    # Verify it's the right layer
                    svc_name = data.get('name', '').lower()
                    if layer_name.lower() in svc_name or svc_name in layer_name.lower():
                        return None  # Current number is correct
        except:
            pass

        # Try to find correct number from service catalog
        try:
            # Get to service root
            if '/MapServer' in base_url:
                service_url = base_url.rsplit('/MapServer', 1)[0] + '/MapServer'
            elif '/FeatureServer' in base_url:
                service_url = base_url.rsplit('/FeatureServer', 1)[0] + '/FeatureServer'
            else:
                service_url = base_url

            response = requests.get(
                f"{service_url}?f=json",
                timeout=5,
                verify=False,
                headers={'User-Agent': 'Mozilla/5.0'}
            )

            if response.status_code == 200:
                data = response.json()

                # Look for exact name match first
                for layer_info in data.get('layers', []):
                    if layer_info.get('name', '').lower() == layer_name.lower():
                        return layer_info.get('id')

                # Then partial match
                for layer_info in data.get('layers', []):
                    svc_name = layer_info.get('name', '').lower()
                    if layer_name.lower() in svc_name or svc_name in layer_name.lower():
                        return layer_info.get('id')
        except:
            pass

        return None