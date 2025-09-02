# management/commands/fix_scrc_layers.py

from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import Layer, Server
import requests
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Fix SCRC layer names to match server configuration'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be changed without making changes',
        )
        parser.add_argument(
            '--server-name',
            type=str,
            default='SCRC',
            help='Server name to fix (default: SCRC)',
        )
        parser.add_argument(
            '--delete-orphans',
            action='store_true',
            help='Delete layers that do not exist on server',
        )
        parser.add_argument(
            '--test',
            action='store_true',
            help='Test fixed layers after updating',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        server_name = options['server_name']
        delete_orphans = options['delete_orphans']
        test_after = options['test']

        self.stdout.write(f"{'[DRY RUN] ' if dry_run else ''}Fixing {server_name} layers...")

        # Get server
        servers = Server.objects.filter(name__icontains=server_name)
        if not servers.exists():
            self.stdout.write(self.style.ERROR(f"No server found matching '{server_name}'"))
            return

        server = servers.first()
        self.stdout.write(f"Using server: {server.name} ({server.url})")

        # Get actual layers from server
        try:
            url = f"{server.url.rstrip('/')}?f=json"
            response = requests.get(url, verify=False, timeout=10)
            response.raise_for_status()
            server_data = response.json()

            if 'error' in server_data:
                self.stdout.write(self.style.ERROR(f"Server error: {server_data['error'].get('message')}"))
                return

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to fetch server data: {e}"))
            return

        # Build mapping of number to name
        server_layers = {}
        for layer_info in server_data.get('layers', []):
            server_layers[layer_info['id']] = {
                'name': layer_info['name'],
                'type': layer_info.get('type'),
                'geometryType': layer_info.get('geometryType')
            }

        self.stdout.write(f"Found {len(server_layers)} layers on server")

        # Get database layers
        db_layers = Layer.objects.filter(server=server)
        self.stdout.write(f"Found {db_layers.count()} layers in database")

        # Track changes
        fixed = []
        orphaned = []
        unchanged = []

        with transaction.atomic():
            for layer in db_layers:
                if layer.number in server_layers:
                    correct_info = server_layers[layer.number]
                    correct_name = correct_info['name']

                    if layer.name != correct_name:
                        old_name = layer.name

                        if not dry_run:
                            layer.name = correct_name
                            # Update type if available
                            if correct_info.get('geometryType'):
                                geom_type = correct_info['geometryType'].lower()
                                if 'point' in geom_type:
                                    layer.type = 'point'
                                elif 'polyline' in geom_type:
                                    layer.type = 'polyline'
                                elif 'polygon' in geom_type:
                                    layer.type = 'polygon'
                            layer.save()

                        fixed.append({
                            'id': layer.layer_id,
                            'old_name': old_name,
                            'new_name': correct_name,
                            'number': layer.number
                        })

                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  {'[WOULD FIX]' if dry_run else '✓'} Layer {layer.layer_id}: "
                                f"'{old_name}' -> '{correct_name}'"
                            )
                        )
                    else:
                        unchanged.append(layer.name)
                else:
                    orphaned.append({
                        'id': layer.layer_id,
                        'name': layer.name,
                        'number': layer.number
                    })

                    self.stdout.write(
                        self.style.WARNING(
                            f"  ⚠ Layer {layer.layer_id} '{layer.name}' "
                            f"(number {layer.number}) not found on server"
                        )
                    )

                    if delete_orphans and not dry_run:
                        layer.delete()
                        self.stdout.write(self.style.ERROR(f"    Deleted orphaned layer"))

        # Summary
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write(self.style.SUCCESS("Summary:"))
        self.stdout.write(f"  Fixed: {len(fixed)}")
        self.stdout.write(f"  Unchanged: {len(unchanged)}")
        self.stdout.write(f"  Orphaned: {len(orphaned)}")

        if fixed:
            self.stdout.write("\nFixed layers:")
            for item in fixed[:10]:
                self.stdout.write(f"  - {item['old_name']} -> {item['new_name']}")

        if orphaned and not delete_orphans:
            self.stdout.write(
                self.style.WARNING(
                    f"\n{len(orphaned)} orphaned layers found. "
                    "Use --delete-orphans to remove them."
                )
            )

        # Test if requested
        if test_after and not dry_run and fixed:
            self.stdout.write("\n" + "=" * 50)
            self.stdout.write("Testing fixed layers...")

            from core.views import fetch_layer_features_with_attributes

            # Test bounds (Sunshine Coast area)
            test_bounds = {
                'minx': 152.9,
                'miny': -26.7,
                'maxx': 153.1,
                'maxy': -26.5
            }

            # Test first 3 fixed layers
            for item in fixed[:3]:
                layer = Layer.objects.get(layer_id=item['id'])
                self.stdout.write(f"\nTesting: {layer.name}")

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
                        self.stdout.write(
                            self.style.SUCCESS(f"  ✓ Found {len(features)} features")
                        )
                    else:
                        self.stdout.write(
                            self.style.WARNING(f"  ⚠ No features in test area")
                        )

                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f"  ✗ Error: {str(e)[:100]}")
                    )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "\nThis was a dry run. Use without --dry-run to apply changes."
                )
            )