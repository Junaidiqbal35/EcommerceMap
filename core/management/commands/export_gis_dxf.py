import requests
import ezdxf
import sys
import os
import logging
from django.core.management.base import BaseCommand, CommandError
from core.models import Server, Layer

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# Configure logging
logging.basicConfig(
    filename='gis_export.log',
    filemode='a',
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.DEBUG  # Adjust as needed
)
logger = logging.getLogger(__name__)

# Constants
USER_AGENT = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleW'
                  'ebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36'}
OFFSET = 0.002  # Offset for bounding box
OUT_SR = 28356  # Spatial Reference ID
DECIMAL = 3  # Decimal precision
TEXT_HEIGHT = 0.5  # Text height in DXF
TEXT_OFFSET_X = 0.75  # Text X offset
TEXT_OFFSET_Y = 0.75  # Text Y offset
ENABLE_LAYER_OFFSETS = True  # Enable layer offset corrections

# Setup requests session with retries
session = requests.Session()
retries = Retry(total=5, backoff_factor=0.1, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retries)
session.mount('http://', adapter)
session.mount('https://', adapter)
session.headers.update(USER_AGENT)


class Command(BaseCommand):
    help = 'Export GIS data to a DXF file based on provided latitude and longitude.'

    def add_arguments(self, parser):
        parser.add_argument('latitude', type=float, help='Target latitude')
        parser.add_argument('longitude', type=float, help='Target longitude')
        parser.add_argument('output_path', type=str, help='Path to save the output DXF file')

    def handle(self, *args, **options):
        latitude = options['latitude']
        longitude = options['longitude']
        output_path = options['output_path']

        try:
            validate_coordinates(latitude, longitude)
        except ValueError as ve:
            raise CommandError(f"Invalid coordinates: {ve}")

        # Ensure the output directory exists
        output_dir = os.path.dirname(output_path)
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
                self.stdout.write(self.style.NOTICE(f"Created directory: {output_dir}"))
            except OSError as e:
                raise CommandError(f"Failed to create directory {output_dir}: {e}")

        # Proceed to create DXF
        try:
            create_GISDXF(latitude, longitude, output_path)
            self.stdout.write(self.style.SUCCESS(f'DXF file successfully created at {output_path}'))
        except Exception as e:
            raise CommandError(f'Error creating DXF file: {e}')


def validate_coordinates(latitude, longitude):
    if not (-90 <= latitude <= 90):
        raise ValueError("Latitude must be between -90 and 90 degrees.")
    if not (-180 <= longitude <= 180):
        raise ValueError("Longitude must be between -180 and 180 degrees.")


def get_target_servers(latitude, longitude):
    """
    Fetch servers from the database where the target point is within their extent.
    """
    target_servers = Server.objects.filter(
        extent_min_x__lt=longitude,
        extent_max_x__gt=longitude,
        extent_min_y__lt=latitude,
        extent_max_y__gt=latitude
    )
    return target_servers


def compile_layers(latitude, longitude):
    target_servers = get_target_servers(latitude, longitude)
    layers = []

    for server in target_servers:
        # reading server and layer data from database.
        server_layers = server.layers.all()
        for l in server_layers:
            l.url = server.url.rstrip('/') + '/' + str(l.number)
            layers.append(l)

    return layers


def insert_blocks(doc):
    """
    Insert predefined blocks into the DXF document.
    """
    # Define blocks as per original script
    blocks = [
        {
            'name': 'valve',
            'entities': [
                ('POLYLINE', {'points': [[-0.5, -0.25], [-0.5, 0.25], [0.5, -0.25], [0.5, 0.25]], 'closed': True}),
                ('SOLID', {'points': [[-0.5, -0.25], [-0.5, 0.25], [0.5, -0.25], [0.5, 0.25]]})
            ]
        },
        {
            'name': 'hydrant',
            'entities': [
                ('CIRCLE', {'center': (0, 0), 'radius': 0.25}),
                ('TEXT', {'text': 'FH', 'insert': (TEXT_OFFSET_X, TEXT_OFFSET_Y), 'height': TEXT_HEIGHT})
            ]
        },
        {
            'name': 'elec_pillar',
            'entities': [
                ('POLYLINE', {'points': [[-0.5, -0.5], [-0.5, 0.5], [0.5, 0.5], [0.5, -0.5]], 'closed': True}),
                ('TEXT', {'text': 'EP', 'insert': (TEXT_OFFSET_X, TEXT_OFFSET_Y), 'height': TEXT_HEIGHT})
            ]
        },
        {
            'name': 'elec_pole',
            'entities': [
                ('CIRCLE', {'center': (0, 0), 'radius': 0.25}),
                ('TEXT', {'text': 'PP', 'insert': (TEXT_OFFSET_X, TEXT_OFFSET_Y), 'height': TEXT_HEIGHT})
            ]
        },
        {
            'name': 'maintenance_hole',
            'entities': [
                ('CIRCLE', {'center': (0, 0), 'radius': 0.525}),
                ('TEXT', {'text': 'MH', 'insert': (TEXT_OFFSET_X, TEXT_OFFSET_Y), 'height': TEXT_HEIGHT})
            ]
        },
        {
            'name': 'maintenance_shaft',
            'entities': [
                ('CIRCLE', {'center': (0, 0), 'radius': 0.3}),
                ('LINE', {'start': (-0.21213, -0.21213), 'end': (0.21213, 0.21213)}),
                ('LINE', {'start': (-0.21213, 0.21213), 'end': (0.21213, -0.21213)}),
                ('TEXT', {'text': 'MS', 'insert': (TEXT_OFFSET_X, TEXT_OFFSET_Y), 'height': TEXT_HEIGHT})
            ]
        },
    ]

    for block in blocks:
        blk = doc.blocks.new(name=block['name'])
        for entity_type, params in block['entities']:
            if entity_type == 'POLYLINE':
                dxfattribs = {'closed': params.get('closed', False)}
                blk.add_polyline2d(params['points'], dxfattribs=dxfattribs)
            elif entity_type == 'SOLID':
                blk.add_solid(points=params['points'])
            elif entity_type == 'CIRCLE':
                blk.add_circle(center=params['center'], radius=params['radius'])
            elif entity_type == 'TEXT':
                blk.add_text(text=params['text'], dxfattribs={
                    'insert': params['insert'],
                    'height': params['height']
                })
            elif entity_type == 'LINE':
                blk.add_line(start=params['start'], end=params['end'])
    return doc


def create_GISDXF(latitude, longitude, output_dxf_path):
    layers = compile_layers(latitude, longitude)

    # Initialize a new DXF document
    doc = ezdxf.new(dxfversion='R2010')
    msp = doc.modelspace()
    insert_blocks(doc)

    for l in layers:
        try:
            if l.type in ['polyline', 'polygon']:
                url = f"{l.url}/query?f=json&where=1%3D1&returnGeometry=true&geometry={longitude - OFFSET}%2C{latitude + OFFSET}%2C{longitude + OFFSET}%2C{latitude - OFFSET}&geometryType=esriGeometryEnvelope&inSR=4326&spatialRel=esriSpatialRelEnvelopeIntersects&outFields=*&outSR={OUT_SR}"
            elif l.type == 'point':
                url = f"{l.url}/query?f=json&where=1%3D1&returnGeometry=true&geometry={longitude - OFFSET}%2C{latitude + OFFSET}%2C{longitude + OFFSET}%2C{latitude - OFFSET}&geometryType=esriGeometryEnvelope&inSR=4326&spatialRel=esriSpatialRelContains&outFields=*&outSR={OUT_SR}"
            else:
                logger.warning(f"Unsupported layer type: {l.type}")
                continue

            response = session.get(url)
            response.raise_for_status()

            json_data = response.json()

            if 'features' in json_data:
                if l.type in ['polyline', 'polygon']:
                    for f in json_data['features']:
                        width = 0
                        for k, v in f['attributes'].items():
                            if 'diam' in k.lower() or 'width' in k.lower():
                                if isinstance(v, (int, float)):
                                    if width == 0:
                                        width = round(v / 1000, DECIMAL)
                        if 'paths' in f['geometry']:
                            for p in f['geometry']['paths']:
                                if ENABLE_LAYER_OFFSETS:
                                    if l.offsetX != 0 or l.offsetY != 0:
                                        p = [[pt[0] + l.offsetX / 1000, pt[1] + l.offsetY / 1000] for pt in p]
                                # Add polyline
                                msp.add_lwpolyline(p, dxfattribs={
                                    'layer': l.name,
                                    'color': 256,
                                    'lineweight': width * 1000
                                })
                        elif 'rings' in f['geometry']:
                            for p in f['geometry']['rings']:
                                msp.add_lwpolyline(p, dxfattribs={
                                    'layer': l.name,
                                    'color': 256,
                                    'lineweight': width * 1000
                                })
                elif l.type == 'point':
                    for f in json_data['features']:
                        x = f['geometry']['x']
                        y = f['geometry']['y']
                        if ENABLE_LAYER_OFFSETS:
                            if l.offsetX != 0 or l.offsetY != 0:
                                x += l.offsetX / 1000
                                y += l.offsetY / 1000

                        layer = l.name.lower()

                        if 'hydrant' in layer:
                            msp.add_blockref('hydrant', insert=(x, y), dxfattribs={'layer': l.name})
                        elif 'valve' in layer:
                            msp.add_blockref('valve', insert=(x, y), dxfattribs={'layer': l.name})
                        elif 'pillar' in layer:
                            msp.add_blockref('elec_pillar', insert=(x, y), dxfattribs={'layer': l.name})
                        elif 'pole' in layer:
                            msp.add_blockref('elec_pole', insert=(x, y), dxfattribs={'layer': l.name})
                        elif 'maintenance' in layer:
                            i = 0  # Initialize counter for text annotations
                            for k, v in f['attributes'].items():
                                if isinstance(v, (int, float)):
                                    if 'diam' in k.lower():
                                        if v > 0.6:
                                            msp.add_blockref('maintenance_hole', insert=(x, y),
                                                             dxfattribs={'layer': l.name})
                                        else:
                                            msp.add_blockref('maintenance_shaft', insert=(x, y),
                                                             dxfattribs={'layer': l.name})
                                        # Add text annotations
                                        msp.add_text(f"%%C {round(v, DECIMAL)}",
                                                     dxfattribs={
                                                         'insert': (x + TEXT_OFFSET_X, y - (i * TEXT_OFFSET_Y)),
                                                         'height': TEXT_HEIGHT,
                                                         'layer': l.name
                                                     })
                                        i += 1
                                    if 'sl' in k.lower():
                                        msp.add_text(f"SL {round(v, DECIMAL)}",
                                                     dxfattribs={
                                                         'insert': (x + TEXT_OFFSET_X, y - (i * TEXT_OFFSET_Y)),
                                                         'height': TEXT_HEIGHT,
                                                         'layer': l.name
                                                     })
                                        i += 1
                                    if 'il' in k.lower():
                                        msp.add_text(f"IL {round(v, DECIMAL)}",
                                                     dxfattribs={
                                                         'insert': (x + TEXT_OFFSET_X, y - (i * TEXT_OFFSET_Y)),
                                                         'height': TEXT_HEIGHT,
                                                         'layer': l.name
                                                     })
                                        i += 1
            print('-----------------------------------------------------------')
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP error occurred: {http_err} on {url}")
            continue
        except ValueError as val_err:
            logger.error(f"Error parsing JSON: {val_err} on {url}")
            continue
        except Exception as err:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            logger.error(f"Unexpected error: {err} on {url}")
            logger.error(f"{exc_type}, {fname}, {exc_tb.tb_lineno}")
            continue

    doc.saveas(output_dxf_path)
