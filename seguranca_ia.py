"""Camada deterministica de defesa contra prompt injection para os assistentes.

Nao substitui autorizacao de conta, PIN, permissoes nem validacao de saida.
Mensagens do usuario e do historico nunca sao instrucoes do sistema.
"""
import re
import unicodedata


def _normalizar(texto):
    n = unicodedata.normalize('NFKD', str(texto or '').casefold())
    return ' '.join(''.join(c for c in n if not unicodedata.combining(c)).split())


# Intentos de elevar o papel do usuario, extrair instrucoes internas ou impor
# fluxo externo. Nao bloqueia simples duvidas tecnicas sobre IA e seguranca.
_PADROES_INJECAO = (
    r'\b(?:ignore|ignora|desconsidere|esqueca|esquece|sobreponha)\b.{0,85}\b(?:instruco(?:es|es)|regras|sistema|prompt|orientacoes|politicas|anterior(?:es)?)\b',
    r'\b(?:revele|mostre|exiba|imprima|copie|vaze|divulgue)\b.{0,90}\b(?:prompt\s*(?:do\s*sistema|interno)|system\s*prompt|instruco(?:es|es)\s*(?:internas|ocultas)|chave(?:s)?\s*(?:api|secretas?))\b',
    r'\b(?:finja|aja|atue|assuma)\b.{0,80}\b(?:administrador|desenvolvedor|system|sistema|root|sem restric(?:ao|oes))\b',
    r'\b(?:voce\s+agora\s+e|a\s+partir\s+de\s+agora\s+voce\s+e)\b.{0,50}\b(?:system|admin|root|desenvolvedor)\b',
    r'(?:\[\s*inst\s*\]|\[\s*/\s*inst\s*\]|<\s*\|\s*im_start\s*\|\s*>|\[\s*system\s*\]|\[\s*developer\s*\])',
    r'\b(?:desative|desabilite|contorne|burle|ignore)\b.{0,75}\b(?:autenticacao|autorizacao|permissoes|verificacao\s*de\s*pin|politica\s*de\s*seguranca)\b',
)
_REGEX_INJECAO = tuple(re.compile(p, re.IGNORECASE | re.DOTALL) for p in _PADROES_INJECAO)


def tentativa_injecao(texto):
    """Indica instrucoes adversariais claras, sem usar o Gemini como guardiao."""
    if not isinstance(texto, str):
        return False
    texto_normal = _normalizar(texto)
    return any(p.search(texto_normal) for p in _REGEX_INJECAO)


def resposta_modelo_insegura(texto):
    """Impede que saidas evidentemente fora do contrato sejam exibidas."""
    if not isinstance(texto, str) or not texto.strip():
        return True
    normal = _normalizar(texto)
    indicadores = (
        r'\b(?:system\s*prompt|prompt\s*interno|instrucoes\s*internas\s*do\s*sistema)\s*[:=]',
        r'\b(?:sua|seu|me\s+envie|informe|digite|compartilhe)\b.{0,48}\b(?:pin|senha|cvv|token\s*de\s*acesso|client\s*secret)\b',
        r'\b(?:ignore\s+as\s+regras|desative\s+a\s+seguranca|acesso\s*irrestrito\s*ao\s*banco)\b',
    )
    return any(re.search(p, normal, re.IGNORECASE) for p in indicadores)
