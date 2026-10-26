"""Exemplo para o SERVIDOR do sistema integrado. Importar nao faz cobrancas.

Configure ARKHE_API_URL, ARKHE_CLIENT_ID e ARKHE_CLIENT_SECRET no ambiente.
Guarde os IDs retornados junto ao pedido do seu sistema.
Em falha de conexao, confira o recebimento antes de cobrar novamente.
As funcoes abaixo nao repetem requisicoes automaticamente.
"""
import os
import uuid
import requests


URL = os.environ.get('ARKHE_API_URL', 'http://127.0.0.1:5000').rstrip('/')
HEADERS = {
    'X-Client-ID': os.environ.get('ARKHE_CLIENT_ID', ''),
    'X-Client-Secret': os.environ.get('ARKHE_CLIENT_SECRET', '')
}


def emitir_boleto(documento_pagador, valor, data_vencimento):
    resposta = requests.post(URL + '/api/v1/cobrancas/boletos', headers=HEADERS, json={
        'documento_pagador': documento_pagador,
        'valor': valor,
        'data_vencimento': data_vencimento
    }, timeout=30)
    resultado = resposta.json()
    if not resposta.ok:
        raise ValueError(resultado.get('mensagem', 'Erro ao emitir boleto'))
    return resultado


def consultar_boleto(id_cobranca):
    resposta = requests.get(URL + f'/api/v1/cobrancas/boletos/{id_cobranca}', headers=HEADERS, timeout=30)
    resultado = resposta.json()
    if not resposta.ok:
        raise ValueError(resultado.get('mensagem', 'Erro ao consultar boleto'))
    return resultado


def baixar_boleto(id_cobranca, arquivo):
    resposta = requests.get(URL + f'/api/v1/cobrancas/boletos/{id_cobranca}/pdf', headers=HEADERS, timeout=30)
    if not resposta.ok:
        raise ValueError(resposta.json().get('mensagem', 'Erro ao baixar boleto'))
    with open(arquivo, 'wb') as destino:
        destino.write(resposta.content)


def vender_cartao(numero_cartao, validade, cvv, valor, tipo='DEBITO', parcelas=1, chave_idempotencia=None):
    chave = chave_idempotencia or uuid.uuid4().hex
    headers = {**HEADERS, 'X-Idempotency-Key': chave}
    resposta = requests.post(URL + '/api/v1/vendas/cartao', headers=headers, json={
        'numero_cartao': numero_cartao,
        'validade': validade,
        'cvv': cvv,
        'valor': valor,
        'tipo': tipo,
        'parcelas': parcelas
    }, timeout=30)
    resultado = resposta.json()
    if not resposta.ok:
        raise ValueError(resultado.get('mensagem', 'Erro ao realizar venda'))
    return resultado


def consultar_movimentacoes(data_inicio, data_fim):
    resposta = requests.get(URL + '/api/v1/movimentacoes', headers=HEADERS, params={
        'data_inicio': data_inicio, 'data_fim': data_fim
    }, timeout=30)
    resultado = resposta.json()
    if not resposta.ok:
        raise ValueError(resultado.get('mensagem', 'Erro ao consultar movimentacoes'))
    return resultado


def gerar_qrcode_pix(valor=None):
    # Sem valor, quem paga escolhe a quantia no Arkhe.
    dados = {'valor_livre': True} if valor is None else {'valor': valor}
    resposta = requests.post(URL + '/api/v1/cobrancas/pix/qrcode', headers=HEADERS,
                             json=dados, timeout=30)
    resultado = resposta.json()
    if not resposta.ok:
        raise ValueError(resultado.get('mensagem', 'Erro ao gerar QR Code Pix'))
    return resultado
