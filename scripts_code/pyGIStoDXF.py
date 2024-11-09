import json
import requests
import sdxf
import sys, os

USER_AGENT = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleW'
                  'ebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36'}
OFFSET = 0.002  # offset from target latitude and longitude for bounding box of request
OUT_SR = 28356  #28356 for GDA94 Zone 56 7856 for GDA 2020 Zone 56 3857 (Web Mercator) 4326 for WGS 84 well known id (wkid) for the spatial reference to return the layers in
DECIMAL = 3  # number of decimal points to round to on levels
TEXT_HEIGHT = 0.5  # default text height to insert with
TEXT_OFFSET_X = 0.75
TEXT_OFFSET_Y = 0.75
SERVER_JSON = 'ServerList.json'  # compiled list of server to check extents for requested point
LAYER_JSON = 'LayerList.json'  # compiled list of layer numbers per server with geometry types provide by the server
ENABLE_LAYER_OFFSETS = True  # option to allow layer sifting for corrections

target_lat = -26.68249618
target_long = 152.95859959


def get_target_servers(latitude, longitude):
    target_servers = []

    with open(SERVER_JSON) as data_file:
        data = json.load(data_file)
        for s in data['servers']:
            if len(s['extent']) == 2:
                if latitude > s['extent'][0][1] and latitude < s['extent'][1][1]:
                    if longitude > s['extent'][0][0] and longitude < s['extent'][1][0]:
                        target_servers.append(s)
            elif len(s['extent']) == 4:
                if latitude > s['extent'][1] and latitude < s['extent'][3]:
                    if longitude > s['extent'][0] and longitude < s['extent'][2]:
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


def insert_blocks(drawing):
    b = sdxf.Block('valve')
    b.append(sdxf.PolyLine(points=[[-0.5, -0.25], [-0.5, 0.25], [0.5, -0.25], [0.5, 0.25]], closed=1))
    b.append(sdxf.Solid(points=[[-0.5, -0.25], [-0.5, 0.25], [0.5, -0.25], [0.5, 0.25]], color=0))
    drawing.blocks.append(b)  # table blocks

    b = sdxf.Block('hydrant')
    b.append(sdxf.Circle(center=[0, 0, 0], radius=0.25, color=0))
    b.append(sdxf.Text('FH', point=[TEXT_OFFSET_X, TEXT_OFFSET_Y], height=TEXT_HEIGHT))
    drawing.blocks.append(b)  # table blocks

    b = sdxf.Block('elec_pillar')
    b.append(sdxf.PolyLine(points=[[-0.5, -0.5], [-0.5, 0.5], [0.5, 0.5], [0.5, -0.5]], closed=1))
    b.append(sdxf.Text('EP', point=[TEXT_OFFSET_X, TEXT_OFFSET_Y], height=TEXT_HEIGHT))
    drawing.blocks.append(b)  # table blocks

    b = sdxf.Block('elec_pole')
    b.append(sdxf.Circle(center=[0, 0, 0], radius=0.25, color=0))
    b.append(sdxf.Text('PP', point=[TEXT_OFFSET_X, TEXT_OFFSET_Y], height=TEXT_HEIGHT))
    drawing.blocks.append(b)  # table blocks

    b = sdxf.Block('maintenance_hole')
    b.append(sdxf.Circle(center=[0, 0, 0], radius=0.525, color=0))
    b.append(sdxf.Text('MH', point=[TEXT_OFFSET_X, TEXT_OFFSET_Y], height=TEXT_HEIGHT))
    drawing.blocks.append(b)  # table blocks

    b = sdxf.Block('maintenance_shaft')
    b.append(sdxf.Circle(center=[0, 0, 0], radius=0.3, color=0))
    b.append(sdxf.Line(points=[[-0.21213, -0.21213], [0.21213, 0.21213]], color=0))
    b.append(sdxf.Line(points=[[-0.21213, 0.21213], [0.21213, -0.21213]], color=0))
    b.append(sdxf.Text('MS', point=[TEXT_OFFSET_X, TEXT_OFFSET_Y], height=TEXT_HEIGHT))
    drawing.blocks.append(b)  # table blocks


def create_GISDXF(latitude, longitude, output_dxf_path):
    #ge teh list of layers to call for info, filtered by server extents to contain the requested point
    layers = compile_layers(latitude, longitude)
    #print(layers)
    d = sdxf.Drawing()

    insert_blocks(d)

    for l in layers:
        try:
            if l['type'] == 'polyline' or l['type'] == 'polygon':
                url = l['url'] + "/query?f=json&where=1%3D1&returnGeometry=true&geometry=" + str(
                    longitude - OFFSET) + "%2C" + str(latitude + OFFSET) + "%2C" + str(
                    longitude + OFFSET) + "%2C" + str(
                    latitude - OFFSET) + "&geometryType=esriGeometryEnvelope&inSR=4326&spatialRel=esriSpatialRelEnvelopeIntersects&outFields=*&outSR=" + str(
                    OUT_SR)
            elif l['type'] == 'point':
                url = l['url'] + "/query?f=json&where=1%3D1&returnGeometry=true&geometry=" + str(
                    longitude - OFFSET) + "%2C" + str(latitude + OFFSET) + "%2C" + str(
                    longitude + OFFSET) + "%2C" + str(
                    latitude - OFFSET) + "&geometryType=esriGeometryEnvelope&inSR=4326&spatialRel=esriSpatialRelContains&outFields=*&outSR=" + str(
                    OUT_SR)
            #print(url)
            response = requests.get(url, headers=USER_AGENT)
            response.raise_for_status()  # Raise an exception for non-200 status codes

            # Parse the response content as JSON
            json_data = response.json()

            if 'features' in json_data:
                if l['type'] == 'polyline' or l['type'] == 'polygon':
                    for f in json_data['features']:
                        #print(f)
                        width = 0
                        for k, v in f['attributes'].items():
                            if 'diam' in k.lower() or 'width' in k.lower():
                                if isinstance(v, int) or isinstance(v, float):
                                    if width == 0:  #put check in so a zero width doesnt override a diameter or vice versa
                                        width = round(v / 1000, DECIMAL)
                        if 'paths' in f['geometry']:
                            for p in f['geometry']['paths']:
                                if ENABLE_LAYER_OFFSETS:
                                    if l['offsetX'] > 0 or l['offsetY'] > 0:
                                        #apply the layer offset to the points in the path/polygon
                                        for pt in p:
                                            pt[0] = pt[0] + l['offsetX'] / 1000
                                            pt[1] = pt[1] + l['offsetY'] / 1000

                                d.append(sdxf.PolyLine(points=p, width=width, color=256, layer=l['name']))
                        elif 'rings' in f['geometry']:
                            for p in f['geometry']['rings']:
                                d.append(sdxf.PolyLine(points=p, width=width, color=256, layer=l['name']))
                elif l['type'] == 'point':
                    for f in json_data['features']:
                        x = f['geometry']['x']
                        y = f['geometry']['y']
                        if ENABLE_LAYER_OFFSETS:
                            if l['offsetX'] > 0 or l['offsetY'] > 0:
                                #apply the layer offset to the points in the path/polygon
                                x = x + l['offsetX'] / 1000
                                y = y + l['offsetY'] / 1000

                        layer = l['name'].lower()

                        if 'hydrant' in layer:
                            d.append(sdxf.Insert('hydrant', point=[x, y], layer=l['name']))
                        elif 'valve' in layer:
                            d.append(sdxf.Insert('valve', point=[x, y], layer=l['name']))
                        elif 'pillar' in layer:
                            d.append(sdxf.Insert('elec_pillar', point=[x, y], layer=l['name']))
                        elif 'pole' in layer:
                            d.append(sdxf.Insert('elec_pole', point=[x, y], layer=l['name']))
                        elif 'maintenance' in layer:
                            i = 0
                            for k, v in f['attributes'].items():
                                if isinstance(v, int) or isinstance(v, float):
                                    if 'diam' in k.lower():
                                        if v > 0.6:
                                            d.append(sdxf.Insert('maintenance_hole', point=[x, y], layer=l['name']))
                                        else:
                                            d.append(sdxf.Insert('maintenance_shaft', point=[x, y], layer=l['name']))
                                        d.append(sdxf.Text('%%C ' + str(round(v, DECIMAL)),
                                                           point=[x + TEXT_OFFSET_X, y - (i * TEXT_OFFSET_Y)],
                                                           height=TEXT_HEIGHT, layer=l['name']))
                                        i += 1
                                    if 'sl' in k.lower():
                                        d.append(sdxf.Text('SL ' + str(round(v, DECIMAL)),
                                                           point=[x + TEXT_OFFSET_X, y - (i * TEXT_OFFSET_Y)],
                                                           height=TEXT_HEIGHT, layer=l['name']))
                                        i += 1
                                    if 'il' in k.lower():
                                        d.append(sdxf.Text('IL ' + str(round(v, DECIMAL)),
                                                           point=[x + TEXT_OFFSET_X, y - (i * TEXT_OFFSET_Y)],
                                                           height=TEXT_HEIGHT, layer=l['name']))
                                        i += 1
                #print(json_data)
            print('-----------------------------------------------------------')
            #return json_data

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

    d.saveas(output_dxf_path)


create_GISDXF(target_lat, target_long, 'C:/Users/danie/Desktop/pyGISDXF.dxf')

if __name__ == '__main__':
    import sys

    if len(sys.argv) < 3:
        print("Usage: \npython pyGIStoDXF.py latitude longitude output_filename")
        print("Example: \npython pyGIStoDXF.py -26.68249618 152.95859959 \"C:/Users/Gerald/Desktop/DCDB.dxf\"")
    else:
        latitude = sys.argv[1]
        longitude = sys.argv[2]
        output_file = sys.argv[3]

        create_GISDXF(latitude, longitude, output_file)
