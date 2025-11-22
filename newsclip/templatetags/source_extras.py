# newsclip/templatetags/source_extras.py
from django import template
from urllib.parse import urlparse

register = template.Library()

@register.filter
def domain(value):
    """
    Extrai o domínio de uma URL:
      https://www.exemplo.com/algum → exemplo.com
    """
    try:
        netloc = urlparse(value).netloc
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:
        return value
