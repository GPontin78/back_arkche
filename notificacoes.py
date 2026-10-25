"""Persistencia de notificacoes e despacho tolerante a falhas via outbox."""
import json
import logging
import os
import uuid
import datetime

import redis
from flask import current_app

from banco import con


CATEGORIAS_CONFIGURAVEIS = ('PIX', 'TRANSFERENCIA', 'BOLETO', 'CARTAO', 'INFORMATIVO')
CATEGORIAS_VALIDAS = CATEGORIAS_CONFIGURAVEIS + ('SEGURANCA_CRITICA',)
CANAL_REDIS = 'arkhe:notificacoes:v1'
TEMPO_BLOQUEIO_SEGUNDOS = 60


def _json_limitado(valor):
    serializado = json.dumps(valor or {}, ensure_ascii=False, separators=(',', ':'), default=str)
    if len(serializado) > 4000:
        raise ValueError('Dados de notificacao excedem o limite de 4000 caracteres')
    return serializado


def _chave_segura(chave):
    chave = str(chave or '').strip()
    if not chave:
        raise ValueError('Chave de idempotencia obrigatoria')
    if len(chave) <= 160:
        return chave
    import hashlib
    return hashlib.sha256(chave.encode('utf-8')).hexdigest()


def _preferencia_ativa(cursor, id_usuario, categoria):
    if categoria == 'SEGURANCA_CRITICA':
        return True
    cursor.execute(
        'SELECT ATIVO FROM PREFERENCIA_NOTIFICACAO WHERE ID_USUARIO = ? AND CATEGORIA = ?',
        (id_usuario, categoria)
    )
    preferencia = cursor.fetchone()
    return preferencia is None or int(preferencia[0]) == 1


def _registrar_evento(cursor, *, chave, categoria, id_conta, id_usuario,
                      referencia_tipo, referencia_id, titulo, mensagem, dados,
                      preferencias_obrigatorias=False):
    categoria = str(categoria or '').upper()
    if categoria not in CATEGORIAS_VALIDAS:
        raise ValueError('Categoria de notificacao invalida')
    if not id_usuario:
        raise ValueError('Destinatario de notificacao nao encontrado')

    chave = _chave_segura(chave)
    cursor.execute(
        'SELECT ID_EVENTO FROM EVENTO_NOTIFICACAO_OUTBOX WHERE CHAVE_IDEMPOTENCIA = ?',
        (chave,)
    )
    existente = cursor.fetchone()
    if existente:
        return int(existente[0])

    dados_json = _json_limitado(dados)
    preferencia_ativa = preferencias_obrigatorias or _preferencia_ativa(cursor, id_usuario, categoria)
    publicar = 1 if preferencia_ativa else 0
    cursor.execute(
        '''INSERT INTO EVENTO_NOTIFICACAO_OUTBOX
           (CHAVE_IDEMPOTENCIA, CATEGORIA, ID_CONTA, ID_USUARIO_DESTINO,
            TIPO_REFERENCIA, ID_REFERENCIA, DADOS_JSON, PUBLICAR)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING ID_EVENTO''',
        (chave, categoria, id_conta, id_usuario, referencia_tipo, referencia_id,
         dados_json, publicar)
    )
    id_evento = int(cursor.fetchone()[0])
    cursor.execute(
        '''INSERT INTO NOTIFICACAO
           (ID_EVENTO, ID_CONTA, ID_USUARIO_DESTINO, CATEGORIA, TITULO, MENSAGEM, DADOS_JSON)
           VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING ID_NOTIFICACAO''',
        (id_evento, id_conta, id_usuario, categoria, str(titulo)[:160],
         str(mensagem)[:500], dados_json)
    )
    id_notificacao = int(cursor.fetchone()[0])
    cursor.execute(
        '''INSERT INTO NOTIFICACAO_DESTINATARIO
           (ID_NOTIFICACAO, ID_USUARIO, ID_CONTA, SUPRIMIDA_EM)
           VALUES (?, ?, ?, ?)''',
        (id_notificacao, id_usuario, id_conta, None if preferencia_ativa else _agora_local())
    )
    return id_evento


def _agora_local():
    # Firebird TIMESTAMP nao guarda fuso; manter o padrao local ja usado no backend.
    fuso_sao_paulo = datetime.timezone(datetime.timedelta(hours=-3))
    return datetime.datetime.now(fuso_sao_paulo).replace(tzinfo=None)


def registrar_evento_bancario(cursor, *, chave_operacao, categoria, id_contas,
                               referencia_tipo, referencia_id, valor=None,
                               id_pagador=None, dados_adicionais=None,
                               titulo=None, mensagem=None):
    """Cria uma notificacao por conta titular dentro da transacao atual.

    O historico/evento nunca e enviado a todos os membros de uma conta PJ por
    inferencia. Cada destinatario e o titular registrado em CONTA.ID_USUARIO;
    a consulta das rotas ainda revalida a titularidade/vinculo ativo.
    """
    categoria = str(categoria or '').upper()
    if categoria not in CATEGORIAS_CONFIGURAVEIS:
        raise ValueError('Categoria financeira invalida')
    ids_evento = []
    contas_unicas = []
    for id_conta in id_contas or ():
        if id_conta is not None and int(id_conta) not in contas_unicas:
            contas_unicas.append(int(id_conta))

    for id_conta in contas_unicas:
        cursor.execute('SELECT ID_USUARIO FROM CONTA WHERE ID_CONTA = ?', (id_conta,))
        titular = cursor.fetchone()
        if not titular:
            raise ValueError('Conta destinataria nao encontrada para notificacao')
        id_usuario = int(titular[0])
        direcao = 'saida' if id_pagador is not None and id_conta == int(id_pagador) else 'entrada'
        dados = dict(dados_adicionais or {})
        dados.update({
            'tipo_referencia': referencia_tipo,
            'id_referencia': referencia_id,
            'direcao': direcao,
        })
        if valor is not None:
            dados['valor'] = str(valor)

        if titulo is None or mensagem is None:
            if categoria == 'PIX':
                titulo_padrao = 'Pix enviado' if direcao == 'saida' else 'Pix recebido'
                verbo = 'enviou' if direcao == 'saida' else 'recebeu'
            elif categoria == 'TRANSFERENCIA':
                titulo_padrao = 'Transferencia enviada' if direcao == 'saida' else 'Transferencia recebida'
                verbo = 'transferiu' if direcao == 'saida' else 'recebeu uma transferencia de'
            elif categoria == 'BOLETO':
                titulo_padrao = 'Boleto pago' if direcao == 'saida' else 'Boleto recebido'
                verbo = 'pagou um boleto de' if direcao == 'saida' else 'recebeu um pagamento de boleto de'
            else:
                titulo_padrao = 'Compra no cartao' if direcao == 'saida' else 'Pagamento recebido no cartao'
                verbo = 'realizou uma compra de' if direcao == 'saida' else 'recebeu um pagamento de cartao de'
            quantia = f'R$ {float(valor):.2f}'.replace('.', ',') if valor is not None else 'um valor nao informado'
            titulo_final = titulo or titulo_padrao
            mensagem_final = mensagem or f'Sua conta {verbo} {quantia}.'
        else:
            titulo_final, mensagem_final = titulo, mensagem

        sufixo = f':conta:{id_conta}'
        chave_evento = str(chave_operacao) + sufixo
        ids_evento.append(_registrar_evento(
            cursor,
            chave=chave_evento,
            categoria=categoria,
            id_conta=id_conta,
            id_usuario=id_usuario,
            referencia_tipo=referencia_tipo,
            referencia_id=referencia_id,
            titulo=titulo_final,
            mensagem=mensagem_final,
            dados=dados,
        ))
    return ids_evento


def registrar_evento_seguranca(cursor, *, chave, id_usuario, titulo, mensagem,
                                dados=None, referencia_tipo=None, referencia_id=None):
    """Cria alerta pessoal obrigatorio que ignora preferencias por categoria."""
    return _registrar_evento(
        cursor,
        chave=chave,
        categoria='SEGURANCA_CRITICA',
        id_conta=None,
        id_usuario=int(id_usuario),
        referencia_tipo=referencia_tipo,
        referencia_id=referencia_id,
        titulo=titulo,
        mensagem=mensagem,
        dados=dados,
        preferencias_obrigatorias=True,
    )


def registrar_notificacao_usuario(cursor, *, chave, categoria, id_usuario, id_conta,
                                  titulo, mensagem, dados=None,
                                  referencia_tipo=None, referencia_id=None):
    """Registra uma notificacao de fluxo para o usuario que iniciou a acao.

    Diferente do evento financeiro por titularidade, este helper permite que
    o membro autorizado que criou um agendamento acompanhe seu proprio status.
    As preferencias da categoria continuam sendo respeitadas.
    """
    return _registrar_evento(
        cursor,
        chave=chave,
        categoria=categoria,
        id_conta=id_conta,
        id_usuario=int(id_usuario),
        referencia_tipo=referencia_tipo,
        referencia_id=referencia_id,
        titulo=titulo,
        mensagem=mensagem,
        dados=dados,
    )


def criar_cliente_redis():
    endereco = os.getenv('ARKHE_WHATSAPP_REDIS_URL') or os.getenv('REDIS_URL')
    if not endereco:
        raise RuntimeError('REDIS_URL/ARKHE_WHATSAPP_REDIS_URL nao configurada')
    return redis.Redis.from_url(
        endereco,
        decode_responses=True,
        socket_timeout=3,
        socket_connect_timeout=3,
    )


def tentar_publicar_evento(id_evento, cliente_redis=None):
    """Publica um evento com lease recuperavel; falhas deixam o outbox pendente."""
    cursor = None
    token = str(uuid.uuid4())
    try:
        cursor = con.cursor()
        cursor.execute(
            '''UPDATE EVENTO_NOTIFICACAO_OUTBOX
               SET BLOQUEIO_TOKEN = ?,
                   BLOQUEIO_ATE = DATEADD(60 SECOND TO CURRENT_TIMESTAMP),
                   TENTATIVAS = TENTATIVAS + 1
               WHERE ID_EVENTO = ? AND PUBLICAR = 1 AND PUBLICADO_EM IS NULL
                 AND PROXIMA_TENTATIVA <= CURRENT_TIMESTAMP
                 AND (BLOQUEIO_ATE IS NULL OR BLOQUEIO_ATE < CURRENT_TIMESTAMP)
               RETURNING ID_EVENTO, CHAVE_IDEMPOTENCIA, CATEGORIA, ID_CONTA,
                         ID_USUARIO_DESTINO, DADOS_JSON''',
            (token, int(id_evento))
        )
        evento = cursor.fetchone()
        if not evento:
            con.rollback()
            return False
        con.commit()

        cliente = cliente_redis or criar_cliente_redis()
        id_conta, id_usuario = evento[3], evento[4]
        escopo = f'usuario:{int(id_usuario)}' if id_conta is None else f'conta:{int(id_conta)}'
        mensagem = json.dumps({
            'event_id': int(evento[0]),
            'event_key': evento[1],
            'categoria': evento[2],
            'id_conta': int(id_conta) if id_conta is not None else None,
            'id_usuario': int(id_usuario) if id_usuario is not None else None,
        }, ensure_ascii=False, separators=(',', ':'))
        cliente.publish(f'{CANAL_REDIS}:{escopo}', mensagem)

        cursor.execute(
            '''UPDATE EVENTO_NOTIFICACAO_OUTBOX
               SET PUBLICADO_EM = CURRENT_TIMESTAMP, BLOQUEIO_TOKEN = NULL,
                   BLOQUEIO_ATE = NULL, ERRO_ULTIMO = NULL
               WHERE ID_EVENTO = ? AND BLOQUEIO_TOKEN = ?''',
            (int(id_evento), token)
        )
        con.commit()
        return True
    except Exception as erro:
        try:
            if cursor:
                con.rollback()
                cursor.execute(
                    '''UPDATE EVENTO_NOTIFICACAO_OUTBOX
                       SET PROXIMA_TENTATIVA = DATEADD(30 SECOND TO CURRENT_TIMESTAMP),
                           BLOQUEIO_TOKEN = NULL, BLOQUEIO_ATE = NULL,
                           ERRO_ULTIMO = ?
                       WHERE ID_EVENTO = ? AND BLOQUEIO_TOKEN = ? AND PUBLICADO_EM IS NULL''',
                    (str(erro)[:500], int(id_evento), token)
                )
                con.commit()
        except Exception:
            try:
                con.rollback()
            except Exception:
                pass
            _registrar_log('Nao foi possivel atualizar a tentativa do outbox', erro)
        _registrar_log(f'Evento {id_evento} continua pendente no outbox', erro)
        return False
    finally:
        if cursor:
            cursor.close()


def tentar_publicar_eventos(ids_eventos):
    """Atalho pos-commit; indisponibilidade Redis nao altera o resultado bancario."""
    for id_evento in ids_eventos or ():
        tentar_publicar_evento(id_evento)


def processar_outbox_pendente(limite=100, cliente_redis=None):
    limite = max(1, min(int(limite), 500))
    cursor = con.cursor()
    try:
        cursor.execute(
            f'''SELECT FIRST {limite} ID_EVENTO
                FROM EVENTO_NOTIFICACAO_OUTBOX
                WHERE PUBLICAR = 1 AND PUBLICADO_EM IS NULL
                  AND PROXIMA_TENTATIVA <= CURRENT_TIMESTAMP
                  AND (BLOQUEIO_ATE IS NULL OR BLOQUEIO_ATE < CURRENT_TIMESTAMP)
                ORDER BY ID_EVENTO'''
        )
        ids = [int(row[0]) for row in cursor.fetchall()]
    finally:
        cursor.close()
    return sum(1 for id_evento in ids if tentar_publicar_evento(id_evento, cliente_redis))


def _registrar_log(mensagem, erro):
    try:
        current_app.logger.warning('%s: %s', mensagem, erro)
    except RuntimeError:
        logging.getLogger('arkhe.notificacoes').warning('%s: %s', mensagem, erro)
