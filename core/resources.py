from django.contrib.gis.geos import Point
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

    def before_save_instance(self, instance,  row, **kwargs):

        if instance.offsetX and instance.offsetY:
            instance.geometry = Point(instance.offsetX, instance.offsetY, srid=4326)
        elif instance.server and instance.server.extent_min_x is not None:

            center_x = (instance.server.extent_min_x + instance.server.extent_max_x) / 2
            center_y = (instance.server.extent_min_y + instance.server.extent_max_y) / 2
            instance.geometry = Point(center_x, center_y, srid=4326)

        return super().before_save_instance(instance, row, **kwargs)