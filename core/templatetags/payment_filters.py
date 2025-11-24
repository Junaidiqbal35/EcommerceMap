from django import template

register = template.Library()

@register.filter
def sum_by(queryset, field_name):
    """Sum a specific field in a queryset"""
    try:
        return sum(getattr(item, field_name, 0) for item in queryset)
    except (TypeError, AttributeError):
        return 0