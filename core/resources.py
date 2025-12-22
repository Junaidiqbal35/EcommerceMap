import logging
import requests
from django.contrib.gis.geos import Point, Polygon
from django.contrib.gis.geos.geometry import GEOSGeometry
from django.core.cache import cache
from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget
from .models import Server, Layer
from .gda2020_converter import GDA2020Converter

logger = logging.getLogger(__name__)


class ServerResource(resources.ModelResource):
    """Enhanced Server resource with GDA2020 integration and auto-discovery"""

    class Meta:
        model = Server
        import_id_fields = ('id',)
        fields = ('id', 'name', 'url', 'extent_min_x', 'extent_min_y',
                  'extent_max_x', 'extent_max_y')
        export_order = ('id', 'name', 'url', 'extent_min_x', 'extent_min_y',
                        'extent_max_x', 'extent_max_y')

    def __init__(self):
        super().__init__()
        self.gda_converter = GDA2020Converter()

    def before_save_instance(self, instance, row, **kwargs):
        """Enhanced validation with Australian coordinate system support"""

        # Validate and normalize URL
        if instance.url:
            instance.url = instance.url.strip()
            if not instance.url.endswith('/'):
                instance.url += '/'

        # Validate coordinates are within Australian bounds
        if all(coord is not None for coord in [
            instance.extent_min_x, instance.extent_min_y,
            instance.extent_max_x, instance.extent_max_y
        ]):
            # Check if coordinates are in Australia
            center_lat = (instance.extent_min_y + instance.extent_max_y) / 2
            center_lng = (instance.extent_min_x + instance.extent_max_x) / 2

            if self.gda_converter.is_in_australia(center_lat, center_lng):
                # Get appropriate GDA2020 zone
                zone_info = self.gda_converter.get_zone_info(center_lat, center_lng)
                if zone_info:
                    logger.info(
                        f"Server {instance.id} ({instance.name}) -> {zone_info['description']} - GDA2020 WKID: {zone_info['gda2020_wkid']}")
            else:
                logger.warning(f"Server {instance.id} ({instance.name}) coordinates may be outside Australia")

        # Try to get real extent from service if invalid/missing
        if self._has_invalid_extent(instance):
            self._update_extent_from_service(instance)

        return super().before_save_instance(instance, row, **kwargs)

    def _has_invalid_extent(self, instance):
        """Check if server has invalid extent (global bounds, null, etc.)"""
        if not all([instance.extent_min_x, instance.extent_min_y, instance.extent_max_x, instance.extent_max_y]):
            return True

        # Check for global bounds
        if (instance.extent_min_x <= -180 and instance.extent_max_x >= 180 and
                instance.extent_min_y <= -90 and instance.extent_max_y >= 90):
            return True

        # Check for unreasonably large extents (> state-sized)
        width = abs(instance.extent_max_x - instance.extent_min_x)
        height = abs(instance.extent_max_y - instance.extent_min_y)
        if width > 20 or height > 20:  # Larger than most Australian states
            return True

        return False

    def _update_extent_from_service(self, instance):
        """Try to get real extent from ArcGIS service"""
        if not instance.url or not instance.url.startswith('http'):
            return

        try:
            response = requests.get(
                f"{instance.url.rstrip('/')}?f=json",
                timeout=10,
                headers={'User-Agent': 'Australian-Infrastructure-System/1.0'}
            )

            if response.status_code == 200:
                data = response.json()

                if 'fullExtent' in data:
                    extent = data['fullExtent']

                    # Check if extent is in a projected coordinate system
                    spatial_ref = extent.get('spatialReference', {})
                    wkid = spatial_ref.get('wkid')

                    if wkid and wkid != 4326:
                        # Try to convert from projected to geographic
                        logger.info(f"Service {instance.name} uses projected coordinates (WKID: {wkid})")
                        # You would implement coordinate transformation here
                        # For now, we'll use the values if they seem reasonable

                    xmin, ymin = extent.get('xmin'), extent.get('ymin')
                    xmax, ymax = extent.get('xmax'), extent.get('ymax')

                    # Basic validation - if values seem like Australian lat/lng
                    if (110 <= xmin <= 160 and 110 <= xmax <= 160 and
                            -50 <= ymin <= -10 and -50 <= ymax <= -10):
                        instance.extent_min_x = xmin
                        instance.extent_min_y = ymin
                        instance.extent_max_x = xmax
                        instance.extent_max_y = ymax

                        logger.info(f"Updated extent for {instance.name} from service metadata")

        except Exception as e:
            logger.debug(f"Could not update extent for {instance.name}: {e}")


class LayerResource(resources.ModelResource):
    """Enhanced Layer resource with geometry handling and automatic discovery"""

    server = fields.Field(
        attribute='server',
        widget=ForeignKeyWidget(Server, 'id')
    )

    geometry_wkt = fields.Field(
        attribute='geometry_wkt',
        readonly=False
    )

    class Meta:
        model = Layer
        import_id_fields = ('layer_id',)
        fields = ('layer_id', 'server', 'type', 'number', 'name',
                  'offsetX', 'offsetY', 'symbol', 'insert', 'geometry_wkt')
        export_order = ('layer_id', 'server', 'type', 'number', 'name',
                        'offsetX', 'offsetY', 'symbol', 'insert', 'geometry_wkt')

    def __init__(self):
        super().__init__()
        self.gda_converter = GDA2020Converter()

    def before_save_instance(self, instance, row, **kwargs):
        """Enhanced geometry and validation for all Australian infrastructure"""

        # 1. Handle explicit geometry from WKT
        wkt = getattr(row, 'geometry_wkt', '') if hasattr(row, 'geometry_wkt') else ''
        if hasattr(row, 'get'):
            wkt = row.get('geometry_wkt', '').strip()
        elif hasattr(instance, 'geometry_wkt'):
            wkt = getattr(instance, 'geometry_wkt', '').strip()

        if wkt:
            try:
                geom = GEOSGeometry(wkt, srid=4326)
                if geom.valid:
                    instance.geometry = geom
                    logger.info(f"Layer {instance.layer_id}: Applied WKT geometry")
                else:
                    logger.warning(f"Layer {instance.layer_id}: Invalid WKT geometry")
                    instance.geometry = None
            except Exception as e:
                logger.warning(f"Layer {instance.layer_id}: WKT parsing failed - {e}")
                instance.geometry = None

        # 2. Handle offset coordinates with Australian validation
        if not instance.geometry and instance.offsetX is not None and instance.offsetY is not None:
            if self.gda_converter.is_in_australia(instance.offsetY, instance.offsetX):
                try:
                    instance.geometry = Point(instance.offsetX, instance.offsetY, srid=4326)
                    logger.info(f"Layer {instance.layer_id}: Created geometry from Australian coordinates")
                except Exception as e:
                    logger.warning(f"Layer {instance.layer_id}: Point creation failed - {e}")
                    instance.geometry = None
            else:
                logger.warning(
                    f"Layer {instance.layer_id}: Coordinates ({instance.offsetX}, {instance.offsetY}) outside Australia")

        # 3. Fallback to server extent center
        if not instance.geometry and instance.server:
            try:
                server_center = self._get_server_center(instance.server)
                if server_center and self.gda_converter.is_in_australia(server_center[1], server_center[0]):
                    instance.geometry = Point(server_center[0], server_center[1], srid=4326)
                    instance.offsetX = server_center[0]
                    instance.offsetY = server_center[1]
                    logger.info(f"Layer {instance.layer_id}: Used Australian server center as fallback")
            except Exception as e:
                logger.warning(f"Layer {instance.layer_id}: Server center fallback failed - {e}")

        # 4. Validate layer configuration
        self._validate_layer_config(instance)

        return super().before_save_instance(instance, row, **kwargs)

    def after_save_instance(self, instance, using_transactions, dry_run):
        """Post-save service discovery and GDA2020 zone logging"""
        if not dry_run:
            try:
                # Log GDA2020 zone information
                if instance.geometry:
                    centroid = instance.geometry.centroid
                    zone_info = self.gda_converter.get_zone_info(centroid.y, centroid.x)
                    if zone_info:
                        logger.info(
                            f"Layer {instance.layer_id} ({instance.name}) -> {zone_info['description']} - GDA2020: {zone_info['gda2020_wkid']}")

                # Discover layer metadata
                self._discover_layer_metadata(instance)
            except Exception as e:
                logger.warning(f"Post-save processing failed for {instance.layer_id}: {e}")

        return super().after_save_instance(instance, using_transactions, dry_run)

    def _get_server_center(self, server):
        """Calculate center point of server extent"""
        if all(coord is not None for coord in [
            server.extent_min_x, server.extent_min_y,
            server.extent_max_x, server.extent_max_y
        ]):
            center_x = (server.extent_min_x + server.extent_max_x) / 2
            center_y = (server.extent_min_y + server.extent_max_y) / 2
            return (center_x, center_y)
        return None

    def _validate_layer_config(self, instance):
        """Validate layer configuration"""
        # Ensure layer number is not None
        if instance.number is None:
            instance.number = 0
            logger.info(f"Layer {instance.layer_id}: Set default layer number to 0")

        # Validate name exists
        if not instance.name or instance.name.strip() == '':
            instance.name = f"Layer {instance.number}"
            logger.info(f"Layer {instance.layer_id}: Set default name")

    def _discover_layer_metadata(self, instance):
        """Discover layer metadata from ArcGIS service"""
        if not instance.server or not instance.server.url:
            return

        cache_key = f"layer_metadata_{instance.server.id}_{instance.number}"
        cached_metadata = cache.get(cache_key)

        if cached_metadata is not None:
            return cached_metadata

        try:
            layer_url = f"{instance.server.url.rstrip('/')}/{instance.number}?f=json"
            response = requests.get(
                layer_url,
                timeout=10,
                headers={'User-Agent': 'Australian-Infrastructure-System/1.0'}
            )

            if response.status_code == 200:
                metadata = response.json()

                # Update layer name if not set or generic
                if metadata.get('name') and (not instance.name or instance.name.startswith('Layer')):
                    instance.name = metadata['name']
                    instance.save()
                    logger.info(f"Updated layer name for {instance.layer_id}: {instance.name}")

                # Update geometry type if available
                if metadata.get('geometryType') and not instance.type:
                    geom_type = metadata['geometryType'].replace('esriGeometry', '').lower()
                    type_mapping = {
                        'point': 'point',
                        'multipoint': 'point',
                        'polyline': 'polyline',
                        'polygon': 'polygon'
                    }
                    if geom_type in type_mapping:
                        instance.type = type_mapping[geom_type]
                        instance.save()
                        logger.info(f"Updated layer type for {instance.layer_id}: {instance.type}")

                cache.set(cache_key, metadata, 3600)
                return metadata

        except Exception as e:
            logger.debug(f"Layer metadata discovery failed for {instance.layer_id}: {e}")
            cache.set(cache_key, {}, 300)

        return {}

    def dehydrate_geometry_wkt(self, layer):
        """Export geometry as WKT"""
        if layer.geometry:
            try:
                return layer.geometry.wkt
            except:
                pass
        return ""


def discover_missing_layers_for_all_servers():
    """Discover and create missing layers for ALL servers"""
    from .models import Server, Layer
    from django.db.models import Max

    results = {'created': [], 'errors': [], 'discovered': []}

    for server in Server.objects.all():
        try:
            logger.info(f"Discovering layers for {server.name}")

            # Get existing layer numbers
            existing_numbers = set(server.layers.values_list('number', flat=True))

            # Discover available layers
            discovered_layers = discover_layers_for_server(server)

            for layer_info in discovered_layers:
                layer_number = layer_info.get('id', 0)

                if layer_number not in existing_numbers:
                    # Get next available layer_id
                    max_layer_id = Layer.objects.aggregate(max_id=Max('layer_id'))['max_id'] or 0
                    new_layer_id = max_layer_id + 1

                    # Determine geometry type
                    geometry_type = layer_info.get('geometry_type', '').lower()
                    if 'point' in geometry_type:
                        layer_type = 'point'
                    elif 'line' in geometry_type:
                        layer_type = 'polyline'
                    elif 'polygon' in geometry_type:
                        layer_type = 'polygon'
                    else:
                        layer_type = 'point'  # default

                    # Calculate center point
                    if server.extent_min_x and server.extent_max_x:
                        center_x = (server.extent_min_x + server.extent_max_x) / 2
                        center_y = (server.extent_min_y + server.extent_max_y) / 2
                    else:
                        center_x, center_y = 0, 0

                    # Create layer
                    layer = Layer.objects.create(
                        layer_id=new_layer_id,
                        server=server,
                        type=layer_type,
                        number=layer_number,
                        name=layer_info.get('name', f'Layer {layer_number}'),
                        offsetX=center_x,
                        offsetY=center_y,
                        geometry=Point(center_x, center_y, srid=4326) if center_x and center_y else None
                    )

                    results['created'].append({
                        'server': server.name,
                        'layer': layer.name,
                        'layer_id': new_layer_id
                    })

                    logger.info(f"Created layer {new_layer_id} for {server.name}: {layer.name}")

            results['discovered'].append({
                'server': server.name,
                'layers_found': len(discovered_layers),
                'layers_created': len([l for l in discovered_layers if l.get('id', 0) not in existing_numbers])
            })

        except Exception as e:
            results['errors'].append({
                'server': server.name,
                'error': str(e)
            })
            logger.error(f"Error discovering layers for {server.name}: {e}")

    return results


def discover_layers_for_server(server):
    """Discover all available layers for a specific server"""
    try:
        response = requests.get(
            f"{server.url.rstrip('/')}?f=json",
            timeout=15,
            headers={'User-Agent': 'Australian-Infrastructure-System/1.0'}
        )

        if response.status_code == 200:
            data = response.json()

            if 'layers' in data:
                layers = data['layers']
            elif 'tables' in data:  # Feature service might only have tables
                layers = data['tables']
            else:
                return []

            discovered_layers = []
            for layer_info in layers:
                discovered_layers.append({
                    'id': layer_info.get('id', 0),
                    'name': layer_info.get('name', f"Layer {layer_info.get('id', 0)}"),
                    'geometry_type': layer_info.get('geometryType', 'esriGeometryPoint').replace('esriGeometry',
                                                                                                 '').lower(),
                    'min_scale': layer_info.get('minScale', 0),
                    'max_scale': layer_info.get('maxScale', 0),
                    'type': layer_info.get('type', 'Feature Layer')
                })

            logger.info(f"Discovered {len(discovered_layers)} layers for {server.name}")
            return discovered_layers

    except Exception as e:
        logger.error(f"Layer discovery failed for {server.name}: {e}")

    return []


def validate_australian_coordinates():
    """Validate all coordinates are within Australian bounds"""
    from .models import Server, Layer

    converter = GDA2020Converter()
    results = {'valid_servers': [], 'invalid_servers': [], 'valid_layers': [], 'invalid_layers': []}

    # Check servers
    for server in Server.objects.all():
        if all([server.extent_min_x, server.extent_min_y, server.extent_max_x, server.extent_max_y]):
            center_lat = (server.extent_min_y + server.extent_max_y) / 2
            center_lng = (server.extent_min_x + server.extent_max_x) / 2

            if converter.is_in_australia(center_lat, center_lng):
                zone_info = converter.get_zone_info(center_lat, center_lng)
                results['valid_servers'].append({
                    'server': server,
                    'zone_info': zone_info
                })
            else:
                results['invalid_servers'].append(server)

    # Check layers
    for layer in Layer.objects.all():
        if layer.offsetX is not None and layer.offsetY is not None:
            if converter.is_in_australia(layer.offsetY, layer.offsetX):
                zone_info = converter.get_zone_info(layer.offsetY, layer.offsetX)
                results['valid_layers'].append({
                    'layer': layer,
                    'zone_info': zone_info
                })
            else:
                results['invalid_layers'].append(layer)

    return results