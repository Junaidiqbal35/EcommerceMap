# management/commands/fix_all_infrastructure.py
from django.core.management.base import BaseCommand
from django.db.models import Max
from django.contrib.gis.geos import Point
import requests
import logging
from core.models import Server, Layer
from core.gda2020_converter import GDA2020Converter

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Fix ALL infrastructure layers across Australia - not just Perth'

    def add_arguments(self, parser):
        parser.add_argument(
            '--discover-layers',
            action='store_true',
            help='Discover and create missing layers for ALL servers'
        )
        parser.add_argument(
            '--validate-coordinates',
            action='store_true',
            help='Validate coordinates are within Australia using GDA2020'
        )
        parser.add_argument(
            '--fix-extents',
            action='store_true',
            help='Fix invalid server extents from service metadata'
        )
        parser.add_argument(
            '--test-all-services',
            action='store_true',
            help='Test accessibility of all ArcGIS services'
        )
        parser.add_argument(
            '--server-id',
            type=int,
            help='Process only specific server ID'
        )

    def handle(self, *args, **options):
        self.stdout.write("🗺️  Fixing ALL Australian Infrastructure Layers...")
        self.gda_converter = GDA2020Converter()

        if options['validate_coordinates']:
            self.validate_australian_coordinates()

        if options['fix_extents']:
            self.fix_invalid_extents(options.get('server_id'))

        if options['discover_layers']:
            self.discover_missing_layers(options.get('server_id'))

        if options['test_all_services']:
            self.test_all_services()

        self.stdout.write(self.style.SUCCESS("✅ All Australian infrastructure layers processed!"))

    def validate_australian_coordinates(self):
        """Validate ALL coordinates are within Australia using GDA2020 converter"""
        self.stdout.write("🌏 Validating coordinates for ALL Australian locations...")

        # Validate servers
        invalid_servers = []
        valid_servers = []

        for server in Server.objects.all():
            if all([server.extent_min_x, server.extent_min_y, server.extent_max_x, server.extent_max_y]):
                center_lat = (server.extent_min_y + server.extent_max_y) / 2
                center_lng = (server.extent_min_x + server.extent_max_x) / 2

                if self.gda_converter.is_in_australia(center_lat, center_lng):
                    zone_info = self.gda_converter.get_zone_info(center_lat, center_lng)
                    valid_servers.append((server, zone_info))
                    self.stdout.write(
                        f"  ✅ {server.name} -> {zone_info['description']} (GDA2020: {zone_info['gda2020_wkid']})")
                else:
                    invalid_servers.append(server)
                    self.stdout.write(f"  ⚠️  {server.name} -> Coordinates outside Australia")

        # Validate layers
        invalid_layers = []
        valid_layers = []

        for layer in Layer.objects.all():
            if layer.offsetX is not None and layer.offsetY is not None:
                if self.gda_converter.is_in_australia(layer.offsetY, layer.offsetX):
                    zone_info = self.gda_converter.get_zone_info(layer.offsetY, layer.offsetX)
                    valid_layers.append((layer, zone_info))
                else:
                    invalid_layers.append(layer)
                    self.stdout.write(f"  ⚠️  Layer {layer.layer_id} ({layer.name}) -> Coordinates outside Australia")

        self.stdout.write(f"\n📊 COORDINATE VALIDATION SUMMARY:")
        self.stdout.write(f"  Valid servers: {len(valid_servers)}")
        self.stdout.write(f"  Invalid servers: {len(invalid_servers)}")
        self.stdout.write(f"  Valid layers: {len(valid_layers)}")
        self.stdout.write(f"  Invalid layers: {len(invalid_layers)}")

    def fix_invalid_extents(self, server_id=None):
        """Fix servers with invalid extents (global bounds, etc.)"""
        self.stdout.write("🔧 Fixing invalid server extents...")

        servers = Server.objects.filter(id=server_id) if server_id else Server.objects.all()

        for server in servers:
            needs_fix = False

            # Check for invalid extents
            if not all([server.extent_min_x, server.extent_min_y, server.extent_max_x, server.extent_max_y]):
                needs_fix = True
                reason = "Missing coordinates"
            elif (server.extent_min_x <= -180 and server.extent_max_x >= 180 and
                  server.extent_min_y <= -90 and server.extent_max_y >= 90):
                needs_fix = True
                reason = "Global bounds"
            else:
                width = abs(server.extent_max_x - server.extent_min_x)
                height = abs(server.extent_max_y - server.extent_min_y)
                if width > 25 or height > 25:  # Larger than continent
                    needs_fix = True
                    reason = f"Too large ({width:.1f}° x {height:.1f}°)"

            if needs_fix:
                self.stdout.write(f"  🔧 Fixing {server.name} - {reason}")
                success = self._update_extent_from_service(server)
                if not success:
                    self._apply_regional_extent(server)

    def _update_extent_from_service(self, server):
        """Try to get real extent from ArcGIS service"""
        try:
            response = requests.get(
                f"{server.url.rstrip('/')}?f=json",
                timeout=15,
                headers={'User-Agent': 'Australian-Infrastructure-System/2.0'}
            )

            if response.status_code == 200:
                data = response.json()

                if 'fullExtent' in data:
                    extent = data['fullExtent']
                    xmin, ymin = extent.get('xmin'), extent.get('ymin')
                    xmax, ymax = extent.get('xmax'), extent.get('ymax')

                    # Check if coordinates look like lat/lng
                    if (110 <= xmin <= 160 and 110 <= xmax <= 160 and
                            -50 <= ymin <= -10 and -50 <= ymax <= -10):

                        server.extent_min_x = xmin
                        server.extent_min_y = ymin
                        server.extent_max_x = xmax
                        server.extent_max_y = ymax
                        server.save()

                        self.stdout.write(f"    ✅ Updated from service metadata")
                        return True
                    else:
                        self.stdout.write(f"    ⚠️  Service coordinates don't look like Australian lat/lng")

        except Exception as e:
            self.stdout.write(f"    ❌ Service request failed: {e}")

        return False

    def _apply_regional_extent(self, server):
        """Apply reasonable regional extent based on server name/URL"""
        regional_extents = {
            # State/territory extents
            'wa': (112.0, -35.0, 129.0, -13.5),  # Western Australia
            'nt': (129.0, -26.0, 138.0, -10.0),  # Northern Territory
            'sa': (129.0, -38.0, 141.0, -26.0),  # South Australia
            'qld': (138.0, -29.5, 154.0, -9.0),  # Queensland
            'nsw': (141.0, -37.5, 154.0, -28.0),  # New South Wales
            'vic': (141.0, -39.5, 150.0, -34.0),  # Victoria
            'tas': (144.0, -43.5, 149.0, -40.0),  # Tasmania

            # Major cities
            'perth': (115.5, -32.5, 116.5, -31.0),
            'adelaide': (138.0, -35.5, 139.0, -34.0),
            'melbourne': (144.0, -38.5, 145.5, -37.0),
            'sydney': (150.5, -34.5, 151.5, -33.5),
            'brisbane': (152.5, -28.0, 153.5, -27.0),
            'darwin': (130.5, -13.0, 131.0, -12.0),
            'hobart': (147.0, -43.0, 147.5, -42.5),
            'gold coast': (153.0, -28.5, 153.5, -27.5),
            'logan': (153.0, -28.0, 153.5, -27.5),
            'townsville': (146.5, -19.5, 147.0, -19.0),
            'toowoomba': (151.5, -28.0, 152.0, -27.5),
        }

        server_name_lower = server.name.lower()
        applied_extent = None

        for region, extent in regional_extents.items():
            if region in server_name_lower:
                server.extent_min_x, server.extent_min_y, server.extent_max_x, server.extent_max_y = extent
                server.save()
                applied_extent = region
                break

        if applied_extent:
            self.stdout.write(f"    🎯 Applied {applied_extent.title()} regional extent")
        else:
            # Default to Australia-wide
            server.extent_min_x, server.extent_min_y, server.extent_max_x, server.extent_max_y = (
            113.0, -44.0, 154.0, -10.0)
            server.save()
            self.stdout.write(f"    🌏 Applied Australia-wide extent as fallback")

    def discover_missing_layers(self, server_id=None):
        """Discover and create missing layers for servers without any"""
        self.stdout.write("🔍 Discovering missing layers for ALL infrastructure...")

        servers = Server.objects.filter(id=server_id) if server_id else Server.objects.all()

        servers_without_layers = []
        for server in servers:
            if server.layers.count() == 0:
                servers_without_layers.append(server)

        self.stdout.write(f"Found {len(servers_without_layers)} servers without layers")

        total_created = 0

        for server in servers_without_layers:
            self.stdout.write(f"\n🔧 Processing {server.name}...")

            # First try to discover from service
            discovered_layers = self._discover_layers_from_service(server)

            if discovered_layers:
                created = self._create_layers_from_discovery(server, discovered_layers)
                total_created += created
                self.stdout.write(f"  ✅ Created {created} layers from service discovery")
            else:
                # Fallback to intelligent guessing based on service type
                created = self._create_default_layers(server)
                total_created += created
                self.stdout.write(f"  🎯 Created {created} default layers based on service type")

        self.stdout.write(f"\n📊 LAYER DISCOVERY SUMMARY:")
        self.stdout.write(f"  Total layers created: {total_created}")
        self.stdout.write(f"  Servers processed: {len(servers_without_layers)}")

    def _discover_layers_from_service(self, server):
        """Try to discover actual layers from ArcGIS service"""
        try:
            response = requests.get(
                f"{server.url.rstrip('/')}?f=json",
                timeout=15,
                headers={'User-Agent': 'Australian-Infrastructure-System/2.0'}
            )

            if response.status_code == 200:
                data = response.json()

                layers = data.get('layers', [])
                if not layers:
                    layers = data.get('tables', [])

                discovered = []
                for layer_info in layers:
                    discovered.append({
                        'id': layer_info.get('id', 0),
                        'name': layer_info.get('name', f"Layer {layer_info.get('id', 0)}"),
                        'geometry_type': layer_info.get('geometryType', 'esriGeometryPoint'),
                        'type': layer_info.get('type', 'Feature Layer')
                    })

                return discovered

        except Exception as e:
            self.stdout.write(f"    ⚠️  Service discovery failed: {e}")

        return []

    def _create_layers_from_discovery(self, server, discovered_layers):
        """Create layers from actual service discovery"""
        created_count = 0

        for layer_info in discovered_layers:
            # Determine geometry type
            geom_type = layer_info['geometry_type'].replace('esriGeometry', '').lower()
            if 'point' in geom_type:
                layer_type = 'point'
            elif 'line' in geom_type or 'polyline' in geom_type:
                layer_type = 'polyline'
            elif 'polygon' in geom_type:
                layer_type = 'polygon'
            else:
                layer_type = 'point'

            # Get center coordinates
            center_x, center_y = self._get_server_center(server)

            # Create layer
            max_layer_id = Layer.objects.aggregate(max_id=Max('layer_id'))['max_id'] or 0

            layer = Layer.objects.create(
                layer_id=max_layer_id + 1,
                server=server,
                type=layer_type,
                number=layer_info['id'],
                name=layer_info['name'],
                offsetX=center_x,
                offsetY=center_y,
                geometry=Point(center_x, center_y, srid=4326) if center_x and center_y else None
            )

            created_count += 1
            self.stdout.write(f"    + Layer {layer.layer_id}: {layer.name} ({layer_type}, #{layer.number})")

        return created_count

    def _create_default_layers(self, server):
        """Create intelligent default layers based on server name/URL"""
        layer_configs = []

        name_lower = server.name.lower()
        url_lower = server.url.lower()

        if 'contour' in name_lower or 'elevation' in name_lower:
            layer_configs = [
                {'name': '1m Contours', 'type': 'polyline', 'symbol': 'contour_line'},
                {'name': '5m Contours', 'type': 'polyline', 'symbol': 'contour_line'},
                {'name': '10m Contours', 'type': 'polyline', 'symbol': 'contour_line'}
            ]
        elif 'infrastructure' in name_lower:
            layer_configs = [
                {'name': 'Water Infrastructure', 'type': 'polyline', 'symbol': 'water_main'},
                {'name': 'Sewer Infrastructure', 'type': 'polyline', 'symbol': 'sewer_main'},
                {'name': 'Stormwater Infrastructure', 'type': 'polyline', 'symbol': 'drainage_pipe'},
                {'name': 'Electrical Infrastructure', 'type': 'polyline', 'symbol': 'electrical'},
                {'name': 'Communication Infrastructure', 'type': 'polyline', 'symbol': 'conduit'},
                {'name': 'Utility Points', 'type': 'point', 'symbol': 'utility_point'}
            ]
        elif 'communication' in name_lower or 'conduit' in name_lower:
            layer_configs = [
                {'name': 'Communication Conduits', 'type': 'polyline', 'symbol': 'conduit'},
                {'name': 'Communication Pits', 'type': 'point', 'symbol': 'comm_pit'},
                {'name': 'Fiber Cables', 'type': 'polyline', 'symbol': 'fiber_cable'}
            ]
        elif 'water' in name_lower:
            layer_configs = [
                {'name': 'Water Mains', 'type': 'polyline', 'symbol': 'water_main'},
                {'name': 'Water Services', 'type': 'polyline', 'symbol': 'water_service'},
                {'name': 'Hydrants', 'type': 'point', 'symbol': 'hydrant'},
                {'name': 'Water Valves', 'type': 'point', 'symbol': 'valve'}
            ]
        elif 'sewer' in name_lower:
            layer_configs = [
                {'name': 'Gravity Sewers', 'type': 'polyline', 'symbol': 'gravity_sewer'},
                {'name': 'Rising Mains', 'type': 'polyline', 'symbol': 'rising_main'},
                {'name': 'Manholes', 'type': 'point', 'symbol': 'manhole'},
                {'name': 'Pump Stations', 'type': 'point', 'symbol': 'pump_station'}
            ]
        elif 'stormwater' in name_lower or 'drainage' in name_lower:
            layer_configs = [
                {'name': 'Stormwater Pipes', 'type': 'polyline', 'symbol': 'drainage_pipe'},
                {'name': 'Drainage Pits', 'type': 'point', 'symbol': 'drainage_pit'},
                {'name': 'Culverts', 'type': 'polyline', 'symbol': 'culvert'}
            ]
        elif 'electrical' in name_lower or 'power' in name_lower:
            layer_configs = [
                {'name': 'Overhead Lines', 'type': 'polyline', 'symbol': 'overhead_line'},
                {'name': 'Underground Cables', 'type': 'polyline', 'symbol': 'underground_cable'},
                {'name': 'Power Poles', 'type': 'point', 'symbol': 'power_pole'},
                {'name': 'Substations', 'type': 'point', 'symbol': 'substation'}
            ]
        else:
            # Generic infrastructure
            layer_configs = [
                {'name': 'Infrastructure Lines', 'type': 'polyline', 'symbol': 'infrastructure'},
                {'name': 'Infrastructure Points', 'type': 'point', 'symbol': 'infrastructure_point'}
            ]

        # Create the layers
        created_count = 0
        center_x, center_y = self._get_server_center(server)

        for i, config in enumerate(layer_configs):
            max_layer_id = Layer.objects.aggregate(max_id=Max('layer_id'))['max_id'] or 0

            layer = Layer.objects.create(
                layer_id=max_layer_id + 1,
                server=server,
                type=config['type'],
                number=i,
                name=config['name'],
                offsetX=center_x,
                offsetY=center_y,
                symbol=config['symbol'],
                insert=config['name'].replace(' ', '_').upper(),
                geometry=Point(center_x, center_y, srid=4326) if center_x and center_y else None
            )

            created_count += 1
            self.stdout.write(f"    + Layer {layer.layer_id}: {layer.name} ({config['type']}, #{i})")

        return created_count

    def _get_server_center(self, server):
        """Calculate center coordinates of server extent"""
        if all([server.extent_min_x, server.extent_min_y, server.extent_max_x, server.extent_max_y]):
            center_x = (server.extent_min_x + server.extent_max_x) / 2
            center_y = (server.extent_min_y + server.extent_max_y) / 2
            return center_x, center_y
        return 0, 0

    def test_all_services(self):
        """Test accessibility of all ArcGIS services"""
        self.stdout.write("🧪 Testing ALL infrastructure services...")

        results = {'working': [], 'slow': [], 'failed': []}

        for server in Server.objects.all():
            self.stdout.write(f"  Testing {server.name}...")

            try:
                import time
                start_time = time.time()

                response = requests.get(
                    f"{server.url.rstrip('/')}?f=json",
                    timeout=10,
                    headers={'User-Agent': 'Australian-Infrastructure-System/2.0'}
                )

                response_time = time.time() - start_time

                if response.status_code == 200:
                    data = response.json()
                    if 'error' not in data:
                        if response_time > 5:
                            results['slow'].append((server, response_time))
                            self.stdout.write(f"    ⚠️  SLOW: {response_time:.1f}s")
                        else:
                            results['working'].append((server, response_time))
                            self.stdout.write(f"    ✅ OK: {response_time:.1f}s")
                    else:
                        results['failed'].append((server, data['error']))
                        self.stdout.write(f"    ❌ ERROR: {data['error'].get('message', 'Unknown')}")
                else:
                    results['failed'].append((server, f"HTTP {response.status_code}"))
                    self.stdout.write(f"    ❌ HTTP {response.status_code}")

            except requests.exceptions.Timeout:
                results['failed'].append((server, "Timeout"))
                self.stdout.write(f"    ⏰ TIMEOUT")
            except Exception as e:
                results['failed'].append((server, str(e)))
                self.stdout.write(f"    ❌ ERROR: {e}")

        # Summary
        self.stdout.write(f"\n📊 SERVICE TEST SUMMARY:")
        self.stdout.write(f"  Working: {len(results['working'])}")
        self.stdout.write(f"  Slow (>5s): {len(results['slow'])}")
        self.stdout.write(f"  Failed: {len(results['failed'])}")

        if results['failed']:
            self.stdout.write(f"\n❌ FAILED SERVICES:")
            for server, error in results['failed'][:5]:  # Show first 5
                self.stdout.write(f"  - {server.name}: {error}")


# management/commands/export_gda_zones.py
class GDAZoneExportCommand(BaseCommand):
    help = 'Export GDA2020 zone information for all infrastructure'

    def handle(self, *args, **options):
        from core.gda2020_converter import GDA2020Converter
        import json

        converter = GDA2020Converter()
        results = {'servers': [], 'layers': [], 'zones_summary': {}}

        # Analyze servers
        for server in Server.objects.all():
            if all([server.extent_min_x, server.extent_min_y, server.extent_max_x, server.extent_max_y]):
                center_lat = (server.extent_min_y + server.extent_max_y) / 2
                center_lng = (server.extent_min_x + server.extent_max_x) / 2

                if converter.is_in_australia(center_lat, center_lng):
                    zone_info = converter.get_zone_info(center_lat, center_lng, include_gda94=True)
                    results['servers'].append({
                        'id': server.id,
                        'name': server.name,
                        'center_coords': [center_lat, center_lng],
                        'gda2020_wkid': zone_info['gda2020_wkid'],
                        'gda94_wkid': zone_info['gda94_wkid'],
                        'utm_zone': zone_info['utm_zone'],
                        'description': zone_info['description']
                    })

        # Analyze layers
        for layer in Layer.objects.all():
            if layer.offsetX and layer.offsetY:
                if converter.is_in_australia(layer.offsetY, layer.offsetX):
                    zone_info = converter.get_zone_info(layer.offsetY, layer.offsetX, include_gda94=True)
                    results['layers'].append({
                        'id': layer.layer_id,
                        'name': layer.name,
                        'server': layer.server.name if layer.server else 'Unknown',
                        'coords': [layer.offsetY, layer.offsetX],
                        'gda2020_wkid': zone_info['gda2020_wkid'],
                        'gda94_wkid': zone_info['gda94_wkid'],
                        'utm_zone': zone_info['utm_zone'],
                        'description': zone_info['description']
                    })

        # Zone summary
        zone_counts = {}
        for item in results['servers'] + results['layers']:
            zone = item['utm_zone']
            if zone not in zone_counts:
                zone_counts[zone] = {'count': 0, 'description': item['description']}
            zone_counts[zone]['count'] += 1

        results['zones_summary'] = zone_counts

        # Export to file
        with open('gda_zones_export.json', 'w') as f:
            json.dump(results, f, indent=2)

        self.stdout.write("📍 GDA2020 Zone Analysis:")
        for zone, info in zone_counts.items():
            self.stdout.write(f"  Zone {zone}: {info['count']} items - {info['description']}")

        self.stdout.write(f"\n✅ Exported to gda_zones_export.json")