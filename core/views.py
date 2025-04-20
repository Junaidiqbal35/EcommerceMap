from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import ezdxf

from .models import Layer, DownloadRecord


@login_required
def home(request):
    """Renders the main map page (home.html)."""
    return render(request, "home.html")


@login_required
def nearby_layers(request):
    try:
        lat = float(request.GET.get("lat"))
        lng = float(request.GET.get("lng"))
        dist_m = float(request.GET.get("dist", 500))  # default 500 meters
    except (TypeError, ValueError):

        return JsonResponse([], safe=False)

    # Create a Point geometry (PostGIS expects (x=lng, y=lat)).
    user_point = Point(lng, lat, srid=4326)

    # Annotate each Layer with distance=Distance(...)
    # Filter to layers within dist_m. Then order by ascending distance.
    # (distance__lte works in meters because SRID=4326 + the Distance function
    # automatically handles degrees->meters conversion if you have Spheroid distance
    # support enabled. If it doesn't, you might need a geography field or transform().)
    nearby_qs = (
        Layer.objects
        .annotate(distance=Distance("geometry", user_point))
        .filter(distance__lte=dist_m)
        .order_by("distance")
    )

    # Build JSON response
    data = []
    for lyr in nearby_qs:
        data.append({
            "id": lyr.layer_id,
            "name": lyr.name,
            "type": lyr.type,
            # distance.m = distance in meters, DB supports geodesic distance
            "distance_m": round(lyr.distance.m, 1) if lyr.distance is not None else None
        })

    return JsonResponse(data, safe=False)


@login_required
def map_layers(request):
    """
    Returns an array of marker-like data for layers that actually have coordinates.
    - If type='point' and offsetX, offsetY != 0 => interpret offset as lat/long
    - If polygon/line => use geometry centroid if present
    """
    data = []
    layers = Layer.objects.all()

    for lyr in layers:
        layer_type = lyr.type.lower()
        ox, oy = lyr.offsetX, lyr.offsetY

        if layer_type == 'point':

            if (ox != 0 or oy != 0):
                data.append({
                    "id": lyr.layer_id,
                    "name": lyr.name,
                    "type": lyr.type,
                    "lat": oy,
                    "lng": ox
                })
        elif layer_type in ['polygon', 'polyline'] and lyr.geometry:
            centroid = lyr.geometry.centroid
            data.append({
                "id": lyr.layer_id,
                "name": lyr.name,
                "type": lyr.type,
                "lat": centroid.y,
                "lng": centroid.x
            })

    return JsonResponse(data, safe=False)


@login_required
def marker_layers(request):
    marker_id = request.GET.get("marker_id")
    if not marker_id:
        return JsonResponse([], safe=False)

    lyr = Layer.objects.filter(layer_id=marker_id).first()
    if not lyr:
        # If layer ID doesn't exist
        return JsonResponse([], safe=False)

    # Check if valid geometry or offset
    layer_type = lyr.type.lower()
    if layer_type == 'point' and (lyr.offsetX == 0 and lyr.offsetY == 0):
        # no offset => can't download
        return JsonResponse([], safe=False)
    elif layer_type in ['polygon', 'polyline'] and (not lyr.geometry):
        return JsonResponse([], safe=False)

    # Otherwise, we assume it's valid for download
    data = [{
        "id": lyr.layer_id,
        "name": lyr.name,
        "type": lyr.type
    }]
    return JsonResponse(data, safe=False)


@login_required
@csrf_exempt
@require_POST
def export_dxf_multi(request):
    lat = request.POST.get("lat")
    lng = request.POST.get("lng")
    zoom = request.POST.get("zoom")

    try:
        lat = float(lat)
    except:
        lat = None

    try:
        lng = float(lng)
    except:
        lng = None

    try:
        zoom = int(zoom)
    except:
        zoom = None

    user = request.user
    layer_ids = request.POST.getlist("layer_ids[]", [])
    if not layer_ids:
        return JsonResponse({"error": "No layers selected."}, status=400)

    selected_layers = Layer.objects.filter(layer_id__in=layer_ids)
    if not selected_layers.exists():
        return JsonResponse({"error": "No valid layers found."}, status=404)

    # Filter out invalid layers
    valid_layers = []
    for lyr in selected_layers:
        lt = lyr.type.lower()
        if lt == 'point' and (lyr.offsetX == 0 and lyr.offsetY == 0):
            continue
        elif lt in ['polygon', 'polyline'] and not lyr.geometry:
            continue
        valid_layers.append(lyr)

    if not valid_layers:
        return JsonResponse({"error": "All selected layers are invalid or missing geometry."}, status=400)

    # Check user has enough connects
    needed = len(valid_layers)
    if hasattr(user, 'connects'):
        if user.connects < needed:
            return JsonResponse({"error": f"Not enough connects. Need {needed}."}, status=403)
        user.connects -= needed
        user.save()

    # Create DXF
    doc = ezdxf.new(dxfversion="R2010")
    msp = doc.modelspace()

    for lyr in valid_layers:
        lt = lyr.type.lower()
        geom = lyr.geometry

        if lt == 'point':
            # Use offset for single point
            x, y = lyr.offsetX, lyr.offsetY
            msp.add_point((x, y))

        elif lt == 'polyline' and geom:
            # Handle both LineString and MultiLineString
            if geom.geom_type == 'LineString':
                coords = list(geom.coords)
                msp.add_lwpolyline(coords)
            elif geom.geom_type == 'MultiLineString':
                for line in geom:
                    coords = list(line.coords)
                    msp.add_lwpolyline(coords)

        elif lt == 'polygon' and geom:

            if geom.geom_type == 'Polygon':
                _export_polygon(geom, msp)
            elif geom.geom_type == 'MultiPolygon':
                for poly in geom:
                    _export_polygon(poly, msp)

        # Log the download
        DownloadRecord.objects.create(
            user=user,
            layer=lyr,
            latitude=lat,
            longitude=lng,
            zoom=zoom
        )

    response = HttpResponse(content_type="application/dxf")
    response["Content-Disposition"] = 'attachment; filename="selected_layers.dxf"'
    doc.write(response)
    return response


def _export_polygon(polygon, msp):
    exterior_coords = list(polygon.exterior.coords)
    msp.add_lwpolyline(exterior_coords, close=True)

    for hole in polygon.interiors:
        hole_coords = list(hole.coords)
        msp.add_lwpolyline(hole_coords, close=True)
