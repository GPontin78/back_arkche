"""Servicos financeiros compartilhados por rotas e pelo worker agendado."""
import hashlib
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import jsonify

from banco import con
from funcao import data_atual, pode_debitar_saldo, usuario_pode_acessar_conta
from limites import aplicar_limite
from notificacoes import registrar_evento_bancario


COLUNAS_PIX = {
    'email': 'CHAVE_PIX_EMAIL',
    'telefone': 'CHAVE_PIX_TELEFONE',
    'cpf': 'CHAVE_PIX_CPF',
    'cnpj': 'CHAVE_PIX_CNPJ',
    'aleatoria': 'CHAVE_PIX_ALEATORIA',
}


class ErroOperacaoFinanceira(Exception):
    def __init__(self, mensagem, status=400, codigo=None):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status = int(status)
        self.codigo = codigo


def _erro_limite(restricao):
    if not restricao:
        return
    resposta, status = restricao
    dados = resposta.get_json(silent=True) or {}
    raise ErroOperacaoFinanceira(
        dados.get('mensagem', 'Operacao recusada pelos limites da conta'),
        status,
        dados.get('codigo'),
    )


def _normalizar_chave(tipo, chave):
    texto = str(chave or '').strip()
    if tipo in ('cpf', 'cnpj', 'telefone'):
        texto = ''.join(caractere for caractere in texto if caractere.isdigit())
    return texto


def hash_chave_pix(tipo, chave):
    texto = _normalizar_chave(tipo, chave)
    return hashlib.sha256(f'{tipo}\0{texto}'.encode('utf-8')).hexdigest()


def _destinatario_favoritado(id_conta, id_usuario, id_destino):
    if not id_conta or not id_usuario or not id_destino:
        return False
    if not usuario_pode_acessar_conta(id_usuario, id_conta):
        return False
    cursor = con.cursor()
    try:
        cursor.execute(
            '''SELECT FIRST 1 ID_FAVORITO FROM FAVORITO_PIX
               WHERE ID_CONTA = ? AND ID_USUARIO = ?
                 AND ID_CONTA_DESTINO = ? AND ATIVO = 1''',
            (int(id_conta), int(id_usuario), int(id_destino)),
        )
        return cursor.fetchone() is not None
    finally:
        cursor.close()


def executar_pix_para_conta(cursor, id_pagador, id_recebedor, valor, id_usuario,
                            *, destinatario_favorito=None):
    """Executa o Pix validado pela conta, sem commit; o chamador owns a transacao."""
    valor = _valor_monetario_api(valor)
    if valor is None:
        raise ErroOperacaoFinanceira('Informe um valor positivo para realizar o Pix', 400, 'VALOR_INVALIDO')
    if int(id_pagador) == int(id_recebedor):
        raise ErroOperacaoFinanceira('Nao e possivel fazer Pix para a mesma conta', 400)
    for id_conta in sorted({int(id_pagador), int(id_recebedor)}):
        cursor.execute('SELECT ID_CONTA FROM CONTA WHERE ID_CONTA = ? WITH LOCK', (id_conta,))
        if not cursor.fetchone():
            raise ErroOperacaoFinanceira('Conta de origem ou destino indisponivel', 404, 'CONTA_NAO_ENCONTRADA')
    if destinatario_favorito is None:
        destinatario_favorito = _destinatario_favoritado(
            id_pagador, id_usuario, id_recebedor,
        )
    _erro_limite(aplicar_limite(
        cursor, id_pagador, 'TRANSFERENCIA', valor,
        id_usuario=id_usuario,
        destinatario_favorito=bool(destinatario_favorito),
    ))
    if not pode_debitar_saldo(id_pagador, valor):
        raise ErroOperacaoFinanceira('Saldo insuficiente para realizar o Pix', 400, 'SALDO_INSUFICIENTE')
    cursor.execute(
        '''INSERT INTO MOVIMENTACAO (ID_PAGADOR, ID_RECEBEDOR, VALOR, DATA_MOVIMENTACAO)
           VALUES (?, ?, ?, ?) RETURNING ID_MOVIMENTACAO''',
        (id_pagador, id_recebedor, valor, data_atual()),
    )
    id_movimentacao = int(cursor.fetchone()[0])
    eventos = registrar_evento_bancario(
        cursor, chave_operacao=f'movimentacao:{id_movimentacao}', categoria='PIX',
        id_contas=[id_pagador, id_recebedor], referencia_tipo='MOVIMENTACAO',
        referencia_id=id_movimentacao, valor=valor, id_pagador=id_pagador,
    )
    return {'id_movimentacao': id_movimentacao, 'valor': valor, 'eventos': eventos}


def executar_pix_por_chave(cursor, id_pagador, id_usuario, tipo_chave, chave_pix,
                           valor, id_favorito=None):
    tipo_chave = str(tipo_chave or '').lower()
    coluna = COLUNAS_PIX.get(tipo_chave)
    chave_pix = _normalizar_chave(tipo_chave, chave_pix)
    if not coluna or not chave_pix:
        raise ErroOperacaoFinanceira('Tipo ou chave Pix invalida', 400, 'CHAVE_INVALIDA')
    cursor.execute(f'SELECT ID_CONTA FROM CHAVE_PIX WHERE {coluna} = ?', (chave_pix,))
    destinos = cursor.fetchall()
    if not destinos:
        raise ErroOperacaoFinanceira('Chave Pix nao encontrada', 404, 'CHAVE_NAO_ENCONTRADA')
    if len(destinos) != 1:
        raise ErroOperacaoFinanceira('Chave Pix com cadastro ambiguo', 409, 'CHAVE_AMBIGUA')
    id_recebedor = int(destinos[0][0])
    favorito = False
    if id_favorito is not None:
        try:
            id_favorito = int(id_favorito)
            cursor.execute(
                '''SELECT FIRST 1 ID_FAVORITO FROM FAVORITO_PIX
                   WHERE ID_FAVORITO = ? AND ID_CONTA = ? AND ID_USUARIO = ?
                     AND ID_CONTA_DESTINO = ? AND TIPO_CHAVE = ?
                     AND CHAVE_HASH = ? AND ATIVO = 1''',
                (id_favorito, int(id_pagador), int(id_usuario), id_recebedor,
                 tipo_chave, hash_chave_pix(tipo_chave, chave_pix)),
            )
            favorito = cursor.fetchone() is not None
        except (TypeError, ValueError):
            favorito = False
        if not favorito:
            raise ErroOperacaoFinanceira(
                'Este favorito mudou ou foi removido. Localize o destinatario novamente.',
                409, 'FAVORITO_ATUALIZADO',
            )
    elif id_usuario:
        favorito = _destinatario_favoritado(id_pagador, id_usuario, id_recebedor)
    return executar_pix_para_conta(
        cursor, id_pagador, id_recebedor, valor, id_usuario,
        destinatario_favorito=favorito,
    )


def _valor_monetario_api(valor):
    try:
        resultado = Decimal(str(valor)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if not resultado.is_finite() or resultado <= 0 or resultado > Decimal('9999999999999.99'):
            return None
        return resultado
    except (InvalidOperation, TypeError, ValueError):
        return None


def executar_pagamento_cobranca(cursor, id_conta, id_usuario, id_cobranca,
                                valor_solicitado=None):
    try:
        id_cobranca = int(id_cobranca)
    except (TypeError, ValueError) as erro:
        raise ErroOperacaoFinanceira('Cobranca invalida', 400, 'COBRANCA_INVALIDA') from erro
    cursor.execute(
        '''SELECT ID_COBRANCA, ID_PAGADOR, ID_RECEBEDOR, VALOR, STATUS, TIPO_COBRANCA
           FROM COBRANCA WHERE ID_COBRANCA = ?''',
        (id_cobranca,),
    )
    cobranca = cursor.fetchone()
    if not cobranca:
        raise ErroOperacaoFinanceira('Cobranca nao encontrada', 404, 'COBRANCA_NAO_ENCONTRADA')
    id_recebedor = int(cobranca[2])
    if int(id_conta) == id_recebedor:
        raise ErroOperacaoFinanceira('A conta recebedora nao pode pagar a propria cobranca', 400)
    for conta in sorted({int(id_conta), id_recebedor}):
        cursor.execute('SELECT ID_CONTA FROM CONTA WHERE ID_CONTA = ? WITH LOCK', (conta,))
        if not cursor.fetchone():
            raise ErroOperacaoFinanceira('Conta nao encontrada', 404, 'CONTA_NAO_ENCONTRADA')
    cursor.execute(
        'SELECT VALOR, STATUS, TIPO_COBRANCA FROM COBRANCA WHERE ID_COBRANCA = ? WITH LOCK',
        (id_cobranca,),
    )
    atual = cursor.fetchone()
    if not atual or int(atual[1]) != 0:
        raise ErroOperacaoFinanceira('Cobranca ja paga ou indisponivel', 409, 'COBRANCA_INDISPONIVEL')
    valor, tipo = atual[0], int(atual[2] or 0)
    if tipo == 1 and valor is None:
        valor = _valor_monetario_api(valor_solicitado)
    elif valor_solicitado is not None:
        valor_informado = _valor_monetario_api(valor_solicitado)
        if valor_informado is None or valor_informado != valor:
            raise ErroOperacaoFinanceira('O valor desta cobranca e fixo e nao pode ser alterado', 400)
    if valor is None or valor <= 0:
        raise ErroOperacaoFinanceira('Informe um valor positivo para pagar este QR Code', 400)
    _erro_limite(aplicar_limite(
        cursor, id_conta, 'PAGAMENTO', valor, id_usuario=id_usuario,
    ))
    if not pode_debitar_saldo(id_conta, valor):
        raise ErroOperacaoFinanceira('Saldo insuficiente para pagar a cobranca', 400, 'SALDO_INSUFICIENTE')
    cursor.execute(
        '''UPDATE COBRANCA SET STATUS = 1, VALOR = ?, ID_PAGADOR = COALESCE(ID_PAGADOR, ?)
           WHERE ID_COBRANCA = ? AND STATUS = 0 RETURNING ID_COBRANCA''',
        (valor, id_conta, id_cobranca),
    )
    if not cursor.fetchone():
        raise ErroOperacaoFinanceira('Cobranca ja paga ou indisponivel', 409, 'COBRANCA_INDISPONIVEL')
    cursor.execute(
        '''INSERT INTO MOVIMENTACAO (ID_PAGADOR, ID_RECEBEDOR, VALOR, DATA_MOVIMENTACAO, ID_COBRANCA)
           VALUES (?, ?, ?, ?, ?) RETURNING ID_MOVIMENTACAO''',
        (id_conta, id_recebedor, valor, data_atual(), id_cobranca),
    )
    id_movimentacao = int(cursor.fetchone()[0])
    categoria = 'PIX' if tipo == 1 else 'BOLETO'
    eventos = registrar_evento_bancario(
        cursor, chave_operacao=f'movimentacao:{id_movimentacao}', categoria=categoria,
        id_contas=[id_conta, id_recebedor], referencia_tipo='MOVIMENTACAO',
        referencia_id=id_movimentacao, valor=valor, id_pagador=id_conta,
        dados_adicionais={'id_cobranca': id_cobranca},
    )
    return {
        'id_movimentacao': id_movimentacao,
        'valor': valor,
        'id_recebedor': id_recebedor,
        'tipo_cobranca': tipo,
        'eventos': eventos,
    }
