from django.core.management.base import BaseCommand
from core.models import Layer
from django.contrib.gis.geos import Point


class Command(BaseCommand):
    help = 'Update geometry, offsetX, and offsetY fields for all layers'

    def handle(self, *args, **kwargs):
        layers = Layer.objects.all()

        for layer in layers:
            try:
                if layer.offsetX and layer.offsetY and (layer.offsetX != 0 or layer.offsetY != 0):
                    # Use offsetX and offsetY to create geometry
                    self.stdout.write(f'Using existing offsetX and offsetY for Layer {layer.name}: ({layer.offsetX}, {layer.offsetY})')
                    layer.geometry = Point(layer.offsetX, layer.offsetY, srid=4326)
                elif layer.server and layer.server.extent_min_x is not None:
                    # Fallback: Calculate center of server extent and update offsetX, offsetY
                    center_x = (layer.server.extent_min_x + layer.server.extent_max_x) / 2
                    center_y = (layer.server.extent_min_y + layer.server.extent_max_y) / 2
                    self.stdout.write(f'Using server extent for Layer {layer.name}: ({center_x}, {center_y})')

                    # Update offsetX and offsetY with calculated values
                    layer.offsetX = center_x
                    layer.offsetY = center_y
                    layer.geometry = Point(center_x, center_y, srid=4326)

                # Save the updated layer
                layer.save()
                self.stdout.write(self.style.SUCCESS(f'Updated geometry, offsetX, and offsetY for Layer: {layer.name}'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Failed to update Layer {layer.name}: {str(e)}'))

        self.stdout.write(self.style.SUCCESS('Update completed for all layers.'))