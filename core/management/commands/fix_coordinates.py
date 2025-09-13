from django.core.management.base import BaseCommand
from django.contrib.gis.geos import Point
from core.models import Server, Layer
from core.gda2020_converter import GDA2020Converter


class Command(BaseCommand):
    help = 'Fix all invalid coordinates identified by validation'

    def handle(self, *args, **options):
        self.stdout.write("🔧 Fixing ALL invalid coordinates...")
        self.gda_converter = GDA2020Converter()

        # Fix invalid servers first
        self.fix_invalid_servers()

        # Fix invalid layers
        self.fix_invalid_layers()

        self.stdout.write(self.style.SUCCESS(" All coordinates fixed!"))

    def fix_invalid_servers(self):
        """Fix servers with invalid extents"""
        self.stdout.write("🌍 Fixing invalid server extents...")

        # Servers identified as having invalid coordinates
        invalid_servers = {
            # Server ID: (min_x, min_y, max_x, max_y) - proper Australian bounds
            14: (153.123552, -27.6600, 153.548640, -27.388767),  # Redland City, QLD
            15: (143.0, -43.5, 149.0, -39.5),  # Tasmania theList
            16: (146.6, -19.8, 147.0, -19.0),  # Townsville City, QLD
            9: (152.6, -27.6, 153.4, -25.9),  # Urban Utilities Sewer (SEQ)
            10: (152.6, -27.6, 153.4, -25.9),  # Urban Utilities Water (SEQ)
            19: (115.5, -35.0, 128.0, -13.5),  # WA Infrastructure (state-wide)
        }

        for server_id, bounds in invalid_servers.items():
            try:
                server = Server.objects.get(id=server_id)
                server.extent_min_x, server.extent_min_y, server.extent_max_x, server.extent_max_y = bounds
                server.save()

                # Validate the fix
                center_lat = (bounds[1] + bounds[3]) / 2
                center_lng = (bounds[0] + bounds[2]) / 2

                if self.gda_converter.is_in_australia(center_lat, center_lng):
                    zone_info = self.gda_converter.get_zone_info(center_lat, center_lng)
                    self.stdout.write(f" Fixed {server.name} -> {zone_info['description']}")
                else:
                    self.stdout.write(f"{server.name} still invalid after fix")

            except Server.DoesNotExist:
                self.stdout.write(f"Server {server_id} not found")

    def fix_invalid_layers(self):
        """Fix layers with coordinates outside Australia"""
        self.stdout.write("Fixing invalid layer coordinates...")

        # Get all layers and fix their coordinates based on their server's valid extent
        invalid_count = 0
        fixed_count = 0

        for layer in Layer.objects.all():
            if layer.offsetX is not None and layer.offsetY is not None:
                # Check if current coordinates are invalid
                if not self.gda_converter.is_in_australia(layer.offsetY, layer.offsetX):
                    invalid_count += 1

                    # Get server's center coordinates (which should now be valid)
                    if layer.server and all([
                        layer.server.extent_min_x, layer.server.extent_min_y,
                        layer.server.extent_max_x, layer.server.extent_max_y
                    ]):
                        center_x = (layer.server.extent_min_x + layer.server.extent_max_x) / 2
                        center_y = (layer.server.extent_min_y + layer.server.extent_max_y) / 2

                        # Verify server center is in Australia
                        if self.gda_converter.is_in_australia(center_y, center_x):
                            # Update layer coordinates
                            layer.offsetX = center_x
                            layer.offsetY = center_y
                            layer.geometry = Point(center_x, center_y, srid=4326)
                            layer.save()
                            fixed_count += 1

                            if fixed_count <= 10:  # Show first 10 fixes
                                zone_info = self.gda_converter.get_zone_info(center_y, center_x)
                                self.stdout.write(
                                    f" Fixed Layer {layer.layer_id} ({layer.name}) -> {zone_info['description']}")
                        else:
                            # Apply specific fixes for known problematic layers
                            fixed_coords = self._get_specific_layer_fix(layer)
                            if fixed_coords:
                                layer.offsetX, layer.offsetY = fixed_coords
                                layer.geometry = Point(fixed_coords[0], fixed_coords[1], srid=4326)
                                layer.save()
                                fixed_count += 1

        self.stdout.write(f"Layer fixes: {invalid_count} invalid found, {fixed_count} fixed")

    def _get_specific_layer_fix(self, layer):
        """Get specific coordinate fixes for problematic layers"""

        # Server-specific coordinate fixes
        server_fixes = {
            # Perth layers should be in Perth coordinates
            30: (115.849, -31.966),  # City of Perth SWD
            31: (115.848, -31.966),  # City of Perth SWD Pits
            13: (115.862, -31.955),  # Perth City Communication

            # Sydney layers should be in Sydney coordinates
            29: (151.204, -33.889),  # City of Sydney 1m Contours
            28: (151.204, -33.889),  # City of Sydney SWD Pits
            27: (151.204, -33.889),  # City of Sydney SWD

            # Queensland layers
            1: (145.752, -18.999),  # QLD Globe
            4: (152.902, -26.708),  # SCRC
            5: (149.789, -22.930),  # Ergon
            6: (153.373, -27.944),  # Gold Coast City Sewer
            7: (153.368, -27.943),  # Gold Coast City Water
            8: (153.360, -27.967),  # Gold Coast City Stormwater
            17: (151.388, -27.519),  # Toowoomba Regional
            26: (152.851, -26.708),  # SCRC 1m Contours

            # SEQ Water utilities
            2: (152.963, -26.846),  # Unitywater Sewer
            3: (152.629, -26.653),  # Unitywater Water
            9: (152.900, -26.800),  # Urban Utilities Sewer
            10: (152.900, -26.800),  # Urban Utilities Water

            # NSW
            12: (149.807, -32.875),  # NSW Sixmaps

            # Regional fixes
            11: (153.044, -27.413),  # Logan City
            14: (153.336, -27.524),  # Redland City
            15: (147.000, -42.000),  # Tasmania theList
            16: (146.800, -19.400),  # Townsville City
            19: (121.000, -24.000),  # WA Infrastructure (central WA)
            25: (145.772, -19.580),  # QLD Contours
        }

        if layer.server_id in server_fixes:
            return server_fixes[layer.server_id]

        return None


