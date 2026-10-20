"""Central registration point for HTTP API routes."""

from .common import valor_monetario_api
from . import whatsapp
from . import get, post, put, delete, patch

__all__ = ['valor_monetario_api', 'get', 'post', 'put', 'delete', 'patch', 'whatsapp']
