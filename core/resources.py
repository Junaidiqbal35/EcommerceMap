from django.contrib.gis.geos import Point
from django.contrib.gis.geos.geometry import GEOSGeometry
from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget
from .models import Server, Layer


class ServerResource(resources.ModelResource):
    class Meta:
        model = Server
        import_id_fields = ('id',)
        fields = ('id', 'name', 'url', 'extent_min_x', 'extent_min_y', 'extent_max_x', 'extent_max_y')
        export_order = ('id', 'name', 'url', 'extent_min_x', 'extent_min_y', 'extent_max_x', 'extent_max_y')


class LayerResource(resources.ModelResource):
    server = fields.Field(
        attribute='server',
        widget=ForeignKeyWidget(Server, 'id')
    )

    class Meta:
        model = Layer
        import_id_fields = ('layer_id',)
        fields = ('layer_id', 'server', 'type', 'number', 'name', 'offsetX', 'offsetY', 'symbol', 'insert')
        export_order = ('layer_id', 'server', 'type', 'number', 'name', 'offsetX', 'offsetY', 'symbol', 'insert')

    def before_save_instance(self, instance, row, **kwargs):
        # 1) Attempt real geometry from WKT, if present
        wkt = row.get('geometry_wkt', '').strip()
        if wkt:
            try:
                geom = GEOSGeometry(wkt, srid=4326)
                # Optional: check if it's valid or not
                instance.geometry = geom if geom.valid else None
            except:
                instance.geometry = None
        else:
            # 2) If no WKT, try the offset logic (for point layers)
            if instance.offsetX is not None and instance.offsetY is not None:
                # Validate lat/lng range to avoid PROJ error
                if -180 <= instance.offsetX <= 180 and -90 <= instance.offsetY <= 90:
                    instance.geometry = Point(instance.offsetX, instance.offsetY, srid=4326)
                else:
                    # offset out of range -> fallback
                    instance.geometry = None
            # 3) If offset is 0 or None, fallback to server bounding box center
            if (not instance.geometry) and instance.server and instance.server.extent_min_x is not None:
                cx = (instance.server.extent_min_x + instance.server.extent_max_x) / 2
                cy = (instance.server.extent_min_y + instance.server.extent_max_y) / 2
                # optionally clamp if it's out of [-90,90]
                if -180 <= cx <= 180 and -90 <= cy <= 90:
                    instance.geometry = Point(cx, cy, srid=4326)
                else:
                    instance.geometry = None

        return super().before_save_instance(instance, row, **kwargs)