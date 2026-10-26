"""Central registration point for HTTP API routes."""

from .common import valor_monetario_api
from . import whatsapp
from . import notificacoes
from . import get, post, put, delete, patch, cpf_consulta

__all__ = ['valor_monetario_api', 'get', 'post', 'put', 'delete', 'patch', 'whatsapp', 'notificacoes', 'cpf_consulta']
