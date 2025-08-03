import json
import requests
import ezdxf
from ezdxf import colors
from ezdxf.math import Vec3
import sys, os
import math
from gda2020_converter import GDA2020Converter

USER_AGENT = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36'}
OFFSET = 0.002  # offset from target latitude and longitude for bounding box of request
DECIMAL = 3  # number of decimal points to round to on levels
TEXT_HEIGHT = 0.5  # default text height to insert with
TEXT_OFFSET_X = 0.75
TEXT_OFFSET_Y = 0.75
SERVER_JSON = os.path.join(os.path.dirname(__file__),
                           'ServerList.json')  # compiled list of server to check extents for requested point
LAYER_JSON = os.path.join(os.path.dirname(__file__),
                          'LayerList.json')  # compiled list of layer numbers per server with geometry types provide by the server
ENABLE_LAYER_OFFSETS = True  # option to allow layer sifting for corrections


def get_target_servers(latitude, longitude):
    target_servers = []

    with open(SERVER_JSON) as data_file:
        data = json.load(data_file)
        for s in data:
            if latitude > s['extent_min_y'] and latitude < s['extent_max_y']:
                if longitude > s['extent_min_x'] and longitude < s['extent_max_x']:
                    target_servers.append(s)

    return target_servers


def compile_layers(latitude, longitude):
    #get the list of servers where the latitude and longitude is within the listed extent
    target_servers = get_target_servers(latitude, longitude)
    #array of layers to call and add to drawing file if response received
    layers = []
    #def get_server_layers(target_servers)
    with open(LAYER_JSON) as data_file:
        data = json.load(data_file)

        for s in target_servers:
            for l in data['layers']:
                if s['id'] == l['server_id']:
                    #add the layer url for each layer
                    l['url'] = s['url'] + str(l['number'])
                    layers.append(l)

    return layers


def insert_blocks(doc):
    # Create block definitions

    # Valve block
    valve_block = doc.blocks.new(name='valve')
    valve_block.add_lwpolyline([(-0.5, -0.25), (-0.5, 0.25), (0.5, 0.25), (0.5, -0.25)], close=True)
    valve_block.add_solid([(-0.5, -0.25), (-0.5, 0.25), (0.5, 0.25), (0.5, -0.25)],
                          dxfattribs={'color': colors.BLACK})

    # Hydrant block
    hydrant_block = doc.blocks.new(name='hydrant')
    hydrant_block.add_circle((0, 0), radius=0.25, dxfattribs={'color': colors.BLACK})
    hydrant_block.add_text('FH', dxfattribs={
        'insert': (TEXT_OFFSET_X, TEXT_OFFSET_Y),
        'height': TEXT_HEIGHT
    })

    # Electric pillar block
    elec_pillar_block = doc.blocks.new(name='elec_pillar')
    elec_pillar_block.add_lwpolyline([(-0.5, -0.5), (-0.5, 0.5), (0.5, 0.5), (0.5, -0.5)], close=True)
    elec_pillar_block.add_text('EP', dxfattribs={
        'insert': (TEXT_OFFSET_X, TEXT_OFFSET_Y),
        'height': TEXT_HEIGHT
    })

    # Electric pole block
    elec_pole_block = doc.blocks.new(name='elec_pole')
    elec_pole_block.add_circle((0, 0), radius=0.25, dxfattribs={'color': colors.BLACK})
    elec_pole_block.add_text('PP', dxfattribs={
        'insert': (TEXT_OFFSET_X, TEXT_OFFSET_Y),
        'height': TEXT_HEIGHT
    })

    # Maintenance hole block
    maintenance_hole_block = doc.blocks.new(name='maintenance_hole')
    maintenance_hole_block.add_circle((0, 0), radius=0.525, dxfattribs={'color': colors.BLACK})
    maintenance_hole_block.add_text('MH', dxfattribs={
        'insert': (TEXT_OFFSET_X, TEXT_OFFSET_Y),
        'height': TEXT_HEIGHT
    })

    # Maintenance shaft block
    maintenance_shaft_block = doc.blocks.new(name='maintenance_shaft')
    maintenance_shaft_block.add_circle((0, 0), radius=0.3, dxfattribs={'color': colors.BLACK})
    maintenance_shaft_block.add_line((-0.21213, -0.21213), (0.21213, 0.21213),
                                     dxfattribs={'color': colors.BLACK})
    maintenance_shaft_block.add_line((-0.21213, 0.21213), (0.21213, -0.21213),
                                     dxfattribs={'color': colors.BLACK})
    maintenance_shaft_block.add_text('MS', dxfattribs={
        'insert': (TEXT_OFFSET_X, TEXT_OFFSET_Y),
        'height': TEXT_HEIGHT
    })


def line_length(x1, y1, x2, y2):
    dx = x2 - x1
    dy = y2 - y1
    return math.sqrt(dx ** 2 + dy ** 2)


def label_line(msp, x1, y1, x2, y2, label, offset=TEXT_HEIGHT / 2, text_readability=True, layer_name='Text'):
    """
    Draws a text label parallel to a line segment, positioned preferentially
    above or to the left of the line.

    Args:
        msp: Model space object from ezdxf
        x1, y1 (float): Coordinates of the starting point of the line.
        x2, y2 (float): Coordinates of the ending point of the line.
        label (str): The text label to display.
        offset (float): The perpendicular distance from the line midpoint
                        to the text anchor point, in data coordinates. A positive
                        value offsets towards the 'preferred' side (up/left).
        text_readability (bool): If True, flips text orientation 180 degrees
                                 if it would otherwise be upside-down (angled
                                 between 90 and 270 degrees).
        layer_name (str): Layer name for the text
    """
    # --- Calculate line properties ---
    dx = x2 - x1
    dy = y2 - y1
    mid_x = (x1 + x2) / 2.0
    mid_y = (y1 + y2) / 2.0

    # Calculate angle in degrees (-180 to 180)
    angle_rad = math.atan2(dy, dx)
    angle_deg = math.degrees(angle_rad)

    # --- Handle zero-length lines ---
    segment_length = math.sqrt(dx ** 2 + dy ** 2)
    if segment_length == 0:
        # Place text at the point if line has no length
        print(f"Warning: Line for label '{label}' has zero length. Placing label at ({mid_x:.2f}, {mid_y:.2f}).")
        return

    # --- Determine Offset Direction (Prefer Above or Left) ---
    # 1. Calculate a perpendicular vector (rotated +90 degrees counter-clockwise from line vector)
    #    Original vector: (dx, dy)
    #    Perpendicular vector: (-dy, dx)
    perp_dx = -dy
    perp_dy = dx

    # 2. Normalize the perpendicular vector
    norm = math.sqrt(perp_dx ** 2 + perp_dy ** 2)
    # Ensure normalization is safe (already checked segment_length != 0)
    norm_perp_dx = perp_dx / norm
    norm_perp_dy = perp_dy / norm

    # 3. Check the direction of the perpendicular vector:
    #    - We prefer "Up": norm_perp_dy > 0
    #    - OR "Left" (for horizontal lines): norm_perp_dy is near 0, and norm_perp_dx < 0
    #    Use a small tolerance for floating point comparisons near zero
    tolerance = 1e-9
    is_pointing_up = norm_perp_dy > tolerance
    is_horizontal_pointing_left = abs(norm_perp_dy) <= tolerance and norm_perp_dx < -tolerance

    # If the default perpendicular direction is not Up or Left, flip it
    if not (is_pointing_up or is_horizontal_pointing_left):
        norm_perp_dx = -norm_perp_dx
        norm_perp_dy = -norm_perp_dy

    # --- Calculate final text position ---
    text_x = mid_x + (offset * norm_perp_dx)
    text_y = mid_y + (offset * norm_perp_dy)

    # --- Determine text angle and alignment ---
    text_angle = angle_deg

    # Optional: Adjust angle for better readability (avoid upside-down text)
    # Angles between 90 and 270 (exclusive) are generally upside down or close to it
    if text_readability:
        if 90 < abs(text_angle) <= 180:  # Covers (90, 180] and [-180, -90)
            adjusted_angle = text_angle + 180
            # Wrap angle to be within (-180, 180] if needed
            text_angle = (adjusted_angle + 180) % 360 - 180

    # Debug print to verify coordinates
    # print(f"Label '{label}': Line from ({x1:.3f}, {y1:.3f}) to ({x2:.3f}, {y2:.3f})")
    # print(f"  Mid: ({mid_x:.3f}, {mid_y:.3f}), Text: ({text_x:.3f}, {text_y:.3f})")

    # --- Place the text ---
    # Create text layer if it doesn't exist
    try:
        doc = msp.doc
        if layer_name not in doc.layers:
            doc.layers.new(name=layer_name)
    except:
        pass  # Fallback if we can't access doc

    # For ezdxf, when using alignment other than left-baseline, we need to use align_point
    # instead of insert for the text positioning
    msp.add_text(
        text=label,
        dxfattribs={
            'insert': (0, 0, 0),  # Base point (required but not used for aligned text)
            'align_point': (text_x, text_y, 0),  # Actual alignment point
            'height': TEXT_HEIGHT,
            'rotation': text_angle,
            'layer': layer_name,
            'halign': 1,  # Center horizontal alignment (1 = center)
            'valign': 1  # Center vertical alignment (1 = middle)
        }
    )


def create_GISDXF(latitude, longitude, output_dxf_path):
    #get the list of layers to call for info, filtered by server extents to contain the requested point
    layers = compile_layers(latitude, longitude)

    # Create converter instance
    converter = GDA2020Converter()
    out_SR_wkid = converter.get_wkid(latitude, longitude, datum='gda94')
    # Create a new DXF document
    doc = ezdxf.new('R2010')  # Use a modern DXF version
    msp = doc.modelspace()

    # Insert block definitions
    insert_blocks(doc)

    for l in layers:
        try:
            # Create layer if it doesn't exist
            if l['name'] not in doc.layers:
                doc.layers.new(name=l['name'])

            if l['type'] == 'polyline' or l['type'] == 'polygon':
                url = l['url'] + "/query?f=json&where=1%3D1&returnGeometry=true&geometry=" + str(
                    longitude - OFFSET) + "%2C" + str(latitude + OFFSET) + "%2C" + str(
                    longitude + OFFSET) + "%2C" + str(
                    latitude - OFFSET) + "&geometryType=esriGeometryEnvelope&inSR=4326&spatialRel=esriSpatialRelEnvelopeIntersects&outFields=*&outSR=" + str(
                    out_SR_wkid)
            elif l['type'] == 'point':
                url = l['url'] + "/query?f=json&where=1%3D1&returnGeometry=true&geometry=" + str(
                    longitude - OFFSET) + "%2C" + str(latitude + OFFSET) + "%2C" + str(
                    longitude + OFFSET) + "%2C" + str(
                    latitude - OFFSET) + "&geometryType=esriGeometryEnvelope&inSR=4326&spatialRel=esriSpatialRelContains&outFields=*&outSR=" + str(
                    out_SR_wkid)

            response = requests.get(url, headers=USER_AGENT)
            response.raise_for_status()  # Raise an exception for non-200 status codes

            # Parse the response content as JSON
            json_data = response.json()

            if 'features' in json_data:
                if l['type'] == 'polyline' or l['type'] == 'polygon':
                    for f in json_data['features']:
                        label = ''
                        size = ''
                        material = ''
                        width = 0
                        inverts = ''
                        elevation = None

                        for k, v in f['attributes'].items():
                            if 'diam' in k.lower() or 'width' in k.lower():
                                if isinstance(v, int) or isinstance(v, float):
                                    if width == 0:  #put check in so a zero width doesnt override a diameter or vice versa
                                        width = round(v / 1000, DECIMAL)
                                if 'diam' in k.lower():
                                    if int(v) != 0:
                                        size = size + '%%C' + str(v)
                                elif 'width' in k.lower():
                                    if isinstance(v, int) or isinstance(v, float):
                                        if int(v) != 0:
                                            if width < 1:
                                                size = size + str(width * 1000) + 'x'
                                            else:
                                                size = size + str(width) + 'x'
                                elif 'height' in k.lower():
                                    if isinstance(v, int) or isinstance(v, float):
                                        if int(v) != 0:
                                            size = size + str(round(v / 1000, DECIMAL))
                            if 'elev' in k.lower() or 'alti' in k.lower():
                                if isinstance(v, int) or isinstance(v, float):
                                    elevation = round(v, DECIMAL)
                            if 'mat' in k.lower():
                                material = str(v)
                            if 'usil' in k.lower():
                                if isinstance(v, int) or isinstance(v, float):
                                    if int(v) != 0:
                                        inverts = inverts + ' USIL ' + str(round(v, DECIMAL))
                            if 'dsil' in k.lower():
                                if isinstance(v, int) or isinstance(v, float):
                                    if int(v) != 0:
                                        inverts = inverts + ' DSIL ' + str(round(v, DECIMAL))
                            label = size + ' ' + material

                        if 'paths' in f['geometry']:
                            for p in f['geometry']['paths']:
                                if ENABLE_LAYER_OFFSETS:
                                    if l['offsetX'] > 0 or l['offsetY'] > 0:
                                        #apply the layer offset to the points in the path/polygon
                                        for pt in p:
                                            pt[0] = pt[0] + l['offsetX'] / 1000
                                            pt[1] = pt[1] + l['offsetY'] / 1000

                                # Add labels if present
                                if len(label) > 0:
                                    for i, pt in enumerate(p):
                                        if i < len(p) - 1:
                                            if line_length(pt[0], pt[1], p[i + 1][0], p[i + 1][1]) > 2:
                                                label_line(msp, pt[0], pt[1], p[i + 1][0], p[i + 1][1], label,
                                                           offset=(TEXT_HEIGHT + width) / 2)

                                # Add invert labels if present
                                if len(inverts) > 0:
                                    for i, pt in enumerate(p):
                                        if i < len(p) - 1:
                                            if line_length(pt[0], pt[1], p[i + 1][0], p[i + 1][1]) > 2:
                                                label_line(msp, pt[0], pt[1], p[i + 1][0], p[i + 1][1], inverts,
                                                           offset=-2.0 * (TEXT_HEIGHT + width / 2))

                                # Create polyline with proper attributes
                                poly_attribs = {
                                    'color': colors.BYLAYER,
                                    'layer': l['name']
                                }
                                if width > 0:
                                    poly_attribs['const_width'] = width

                                lwpoly = msp.add_lwpolyline(p, dxfattribs=poly_attribs)
                                if elevation is not None:
                                    lwpoly.dxf.elevation = elevation

                        elif 'rings' in f['geometry']:
                            for p in f['geometry']['rings']:
                                if ENABLE_LAYER_OFFSETS:
                                    if l['offsetX'] > 0 or l['offsetY'] > 0:
                                        #apply the layer offset to the points in the path/polygon
                                        for pt in p:
                                            pt[0] = pt[0] + l['offsetX'] / 1000
                                            pt[1] = pt[1] + l['offsetY'] / 1000

                                # Add labels if present
                                if len(label) > 0:
                                    for i, pt in enumerate(p):
                                        if i < len(p) - 1:
                                            if line_length(pt[0], pt[1], p[i + 1][0], p[i + 1][1]) > 2:
                                                label_line(msp, pt[0], pt[1], p[i + 1][0], p[i + 1][1], label,
                                                           offset=TEXT_HEIGHT / 2)

                                # Add invert labels if present
                                if len(inverts) > 0:
                                    for i, pt in enumerate(p):
                                        if i < len(p) - 1:
                                            if line_length(pt[0], pt[1], p[i + 1][0], p[i + 1][1]) > 2:
                                                label_line(msp, pt[0], pt[1], p[i + 1][0], p[i + 1][1], inverts,
                                                           offset=-1.5 * TEXT_HEIGHT)

                                # Create closed polyline (polygon)
                                poly_attribs = {
                                    'color': colors.BYLAYER,
                                    'layer': l['name']
                                }
                                if width > 0:
                                    poly_attribs['const_width'] = width

                                lwpoly = msp.add_lwpolyline(p, close=True, dxfattribs=poly_attribs)
                                if elevation is not None:
                                    lwpoly.dxf.elevation = elevation

                elif l['type'] == 'point':
                    for f in json_data['features']:
                        x = f['geometry']['x']
                        y = f['geometry']['y']
                        if ENABLE_LAYER_OFFSETS:
                            if l['offsetX'] > 0 or l['offsetY'] > 0:
                                #apply the layer offset to the points
                                x = x + l['offsetX'] / 1000
                                y = y + l['offsetY'] / 1000

                        layer = l['name'].lower()

                        if 'hydrant' in layer:
                            msp.add_blockref('hydrant', (x, y), dxfattribs={'layer': l['name']})
                        elif 'valve' in layer:
                            msp.add_blockref('valve', (x, y), dxfattribs={'layer': l['name']})
                        elif 'pillar' in layer:
                            msp.add_blockref('elec_pillar', (x, y), dxfattribs={'layer': l['name']})
                        elif 'pole' in layer:
                            msp.add_blockref('elec_pole', (x, y), dxfattribs={'layer': l['name']})
                        elif 'maintenance' in layer:
                            i = 0
                            for k, v in f['attributes'].items():
                                if isinstance(v, int) or isinstance(v, float):
                                    if 'diam' in k.lower():
                                        if v > 0.6:
                                            msp.add_blockref('maintenance_hole', (x, y),
                                                             dxfattribs={'layer': l['name']})
                                        else:
                                            msp.add_blockref('maintenance_shaft', (x, y),
                                                             dxfattribs={'layer': l['name']})
                                        msp.add_text('%%C ' + str(round(v, DECIMAL)), dxfattribs={
                                            'insert': (x + TEXT_OFFSET_X, y - (i * TEXT_OFFSET_Y)),
                                            'height': TEXT_HEIGHT,
                                            'layer': l['name']
                                        })
                                        i += 1
                                    if 'sl' in k.lower():
                                        msp.add_text('SL ' + str(round(v, DECIMAL)), dxfattribs={
                                            'insert': (x + TEXT_OFFSET_X, y - (i * TEXT_OFFSET_Y)),
                                            'height': TEXT_HEIGHT,
                                            'layer': l['name']
                                        })
                                        i += 1
                                    if 'il' in k.lower():
                                        msp.add_text('IL ' + str(round(v, DECIMAL)), dxfattribs={
                                            'insert': (x + TEXT_OFFSET_X, y - (i * TEXT_OFFSET_Y)),
                                            'height': TEXT_HEIGHT,
                                            'layer': l['name']
                                        })
                                        i += 1

            print('-----------------------------------------------------------')

        except requests.exceptions.HTTPError as http_err:
            print(f"HTTP error occurred: {http_err} on {url}")
            return 0
        except ValueError as val_err:
            print(f"Error parsing JSON: {val_err} on {url}")
            return 0
        except Exception as err:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(f"Unexpected error: {err} on {url}")
            print(exc_type, fname, exc_tb.tb_lineno)
            return 0

    # Save the DXF file
    doc.saveas(output_dxf_path)
    print(f"DXF file saved as: {output_dxf_path}")


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 3:
        print("Usage: \npython pyGIStoDXF.py latitude longitude output_filename")
        print("Example: \npython pyGIStoDXF.py -26.68249618 152.95859959 \"C:/Users/Gerald/Desktop/DCDB.dxf\"")

        latitude = -26.78787754
        longitude = 153.11923026
        output_file = 'C:/Users/danie/Desktop/241208-ServiceBase-250723.dxf'

    else:
        latitude = float(sys.argv[1])
        longitude = float(sys.argv[2])
        output_file = sys.argv[3].strip('"').strip("'")

    create_GISDXF(latitude, longitude, output_file)
