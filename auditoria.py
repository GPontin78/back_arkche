"""Log direto no Firebird separado; o worker termina a entrega da outbox antiga."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import time
import uuid
from datetime import date, datetime

import fdb
import redis
from flask import Response, current_app, g, jsonify, request, stream_with_context

from banco import con
from funcao import descobre_id_conta, descobre_id_usuario
from limites import usuario_eh_admin_bancario


CANAL_AUDITORIA = 'arkhe:admin:audit:v1'
LEASE_SEGUNDOS = 90
_ULTIMO_AVISO_SCHEMA = 0.0
_ULTIMO_AVISO_OUTBOX_HTTP = 0.0


def _admin():
    id_usuario = descobre_id_usuario()
    if not id_usuario:
        return None, (jsonify({'mensagem': 'Autenticacao necessaria'}), 401)
    if not usuario_eh_admin_bancario(id_usuario):
        return None, (jsonify({'mensagem': 'Acesso exclusivo ao administrador bancario'}), 403)
    return int(id_usuario), None


def _conectar_banco_auditoria():
    nome = os.getenv('ARKHE_AUDIT_DB_NAME')
    if not nome:
        raise RuntimeError('Banco de auditoria independente não configurado (ARKHE_AUDIT_DB_NAME).')
    return fdb.connect(
        host=os.getenv('ARKHE_AUDIT_DB_HOST', current_app.config.get('DB_HOST', '127.0.0.1')),
        port=int(os.getenv('ARKHE_AUDIT_DB_PORT', current_app.config.get('DB_PORT', 3050))),
        database=nome,
        user=os.getenv('ARKHE_AUDIT_DB_USER', current_app.config.get('DB_USER', 'SYSDBA')),
        password=os.getenv('ARKHE_AUDIT_DB_PASSWORD', current_app.config.get('DB_PASSWORD', '')),
        charset='UTF8',
    )


def _id_or_none(valor):
    if valor is None or str(valor).strip() == '':
        return None
    try:
        numero = int(valor)
        if numero < 1:
            raise ValueError
        return numero
    except (TypeError, ValueError):
        raise ValueError('Identificador inválido')


def _data_or_none(valor, fim=False):
    if not valor:
        return None
    try:
        data = date.fromisoformat(valor)
        return datetime.combine(data, datetime.max.time() if fim else datetime.min.time())
    except (TypeError, ValueError) as erro:
        raise ValueError('Datas devem usar o formato AAAA-MM-DD') from erro


def _json_data(valor):
    if valor is None:
        return None
    if isinstance(valor, (dict, list)):
        return valor
    try:
        return json.loads(str(valor))
    except (TypeError, ValueError):
        return {'texto': str(valor)}


def _json_timestamp(valor):
    return valor.isoformat(sep=' ') if isinstance(valor, datetime) else str(valor) if valor is not None else None


def _redis():
    endereco = os.getenv('ARKHE_WHATSAPP_REDIS_URL') or os.getenv('REDIS_URL')
    if not endereco:
        raise RuntimeError('Redis não configurado (REDIS_URL).')
    return redis.Redis.from_url(endereco, decode_responses=True, socket_timeout=5, socket_connect_timeout=3)


def _origem_id():
    configuracao = current_app.config
    base = f"{configuracao.get('DB_HOST', '')}:{configuracao.get('DB_PORT', '')}/{configuracao.get('DB_NAME', '')}"
    return os.getenv('ARKHE_AUDIT_SOURCE_ID') or ('arkhe-' + hashlib.sha256(base.encode('utf-8')).hexdigest()[:24])


def _inserir_evento(cursor, evento, resultado, motivo, id_usuario, id_conta,
                    valor, id_registro, operacao, origem, dados):
    # CREATE/EXECUTE são ações do assistente, e não operações DML do Firebird.
    operacao = {'CREATE': 'INSERT', 'EXECUTE': 'UPDATE'}.get(operacao, operacao)
    if operacao not in ('INSERT', 'UPDATE', 'DELETE', 'READ', 'DENY'):
        raise ValueError('Operação de log inválida')
    snapshot = json.dumps(dados or {}, ensure_ascii=False, separators=(',', ':'), default=str)
    if len(snapshot) > 4000:
        raise ValueError('Dados do log excedem 4000 caracteres')
    parametros = (
        str(evento)[:48], operacao, id_registro, id_usuario, id_conta, valor,
        str(resultado)[:24], str(motivo)[:500] if motivo else None,
        str(origem or '/flask')[:160], snapshot,
    )
    cursor.execute("SELECT 1 FROM RDB$TRIGGERS WHERE RDB$TRIGGER_NAME = 'TG_AI_MOVIMENTACAO_LOG'")
    if cursor.fetchone():
        cursor.execute('''EXECUTE BLOCK (
            P_EVENTO VARCHAR(48) = ?, P_OPERACAO VARCHAR(12) = ?,
            P_ID_REGISTRO BIGINT = ?, P_ID_USUARIO INTEGER = ?, P_ID_CONTA INTEGER = ?,
            P_VALOR DECIMAL(18,2) = ?, P_RESULTADO VARCHAR(24) = ?,
            P_MOTIVO VARCHAR(500) = ?, P_ORIGEM VARCHAR(160) = ?, P_DADOS VARCHAR(4000) = ?
        ) AS
        DECLARE VARIABLE V_DESTINO VARCHAR(512);
        DECLARE VARIABLE V_USUARIO VARCHAR(63);
        DECLARE VARIABLE V_SENHA VARCHAR(255);
        DECLARE VARIABLE V_ORIGEM_ID VARCHAR(80);
        BEGIN
            SELECT DATA_SOURCE, USUARIO, SENHA, ORIGEM_ID
            FROM CONFIGURACAO_LOG WHERE ID_CONFIGURACAO = 1
            INTO :V_DESTINO, :V_USUARIO, :V_SENHA, :V_ORIGEM_ID;
            IF (V_DESTINO IS NULL) THEN
                EXCEPTION EX_LOG_CONFIGURACAO;

            EXECUTE STATEMENT (
                'INSERT INTO AUDITORIA_EVENTO (
                    ORIGEM_ID, ID_EVENTO_ORIGEM, EVENTO, TABELA_ORIGEM, OPERACAO,
                    ID_REGISTRO, ID_USUARIO, ID_CONTA, VALOR, RESULTADO, MOTIVO,
                    ORIGEM, DADOS_NOVOS, CRIADO_EM
                ) VALUES (
                    :origem_id, :id_evento, :evento, ''FLASK'', :operacao,
                    :id_registro, :id_usuario, :id_conta, :valor, :resultado,
                    :motivo, :origem, :dados, :criado_em
                )'
            ) (
                origem_id := :V_ORIGEM_ID,
                id_evento := NEXT VALUE FOR GEN_LOG_EVENTO,
                evento := :P_EVENTO, operacao := :P_OPERACAO,
                id_registro := :P_ID_REGISTRO, id_usuario := :P_ID_USUARIO,
                id_conta := :P_ID_CONTA, valor := :P_VALOR, resultado := :P_RESULTADO,
                motivo := :P_MOTIVO, origem := :P_ORIGEM, dados := :P_DADOS,
                criado_em := CURRENT_TIMESTAMP
            )
            ON EXTERNAL DATA SOURCE :V_DESTINO
            AS USER :V_USUARIO
            PASSWORD :V_SENHA
            WITH COMMON TRANSACTION;
        END''', parametros)
        return True

    # Compatibilidade durante a publicação: antes da migração 011, usa o log atual.
    cursor.execute("SELECT 1 FROM RDB$RELATIONS WHERE RDB$RELATION_NAME = 'AUDITORIA_EVENTO_OUTBOX'")
    if not cursor.fetchone():
        return False
    cursor.execute('''INSERT INTO AUDITORIA_EVENTO_OUTBOX
        (EVENTO, TABELA_ORIGEM, OPERACAO, ID_REGISTRO, ID_USUARIO, ID_CONTA,
         VALOR, RESULTADO, MOTIVO, ORIGEM, DADOS_NOVOS)
        VALUES (?, 'FLASK', ?, ?, ?, ?, ?, ?, ?, ?, ?)''', parametros)
    return True


def registrar_evento_flask(*, evento, resultado, motivo=None, id_usuario=None,
                           id_conta=None, valor=None, id_registro=None,
                           operacao='DENY', origem=None, dados=None, cursor=None,
                           obrigatorio=True):
    """Com cursor, o log participa do commit/rollback da própria operação."""
    global _ULTIMO_AVISO_OUTBOX_HTTP
    if cursor is not None:
        if not _inserir_evento(cursor, evento, resultado, motivo, id_usuario, id_conta,
                              valor, id_registro, operacao, origem, dados):
            raise RuntimeError('Estrutura de log não instalada')
        return True

    conexao = cursor = None
    try:
        conexao = fdb.connect(
            host=current_app.config['DB_HOST'], port=current_app.config['DB_PORT'],
            database=current_app.config['DB_NAME'], user=current_app.config['DB_USER'],
            password=current_app.config['DB_PASSWORD'], charset='UTF8',
        )
        cursor = conexao.cursor()
        if not _inserir_evento(cursor, evento, resultado, motivo, id_usuario, id_conta,
                              valor, id_registro, operacao, origem, dados):
            agora = time.monotonic()
            if agora - _ULTIMO_AVISO_OUTBOX_HTTP >= 60:
                current_app.logger.warning('Outbox de auditoria ainda não está instalado; eventos Flask serão retomados após a migração.')
                _ULTIMO_AVISO_OUTBOX_HTTP = agora
            if obrigatorio:
                raise RuntimeError('Estrutura de log não instalada')
            return False
        conexao.commit()
        return True
    except Exception:
        if conexao:
            try:
                conexao.rollback()
            except Exception:
                pass
        try:
            current_app.logger.exception('Não foi possível persistir o evento no LOG')
        except RuntimeError:
            logging.getLogger('arkhe.auditoria').exception('Falha ao persistir evento Flask')
        if obrigatorio:
            raise
        return False
    finally:
        if cursor:
            cursor.close()
        if conexao:
            conexao.close()


def _registrar_acesso_detalhe(admin_id, recurso, identificador):
    registrar_evento_flask(
        evento='DADO_ADMINISTRATIVO_ACESSADO', resultado='SUCESSO',
        motivo='Consulta administrativa autorizada', id_usuario=admin_id,
        operacao='READ', origem=request.path,
        dados={'recurso': recurso, 'identificador': int(identificador)},
    )


def _preparar_contexto_trigger():
    """Vincula ator e rota à conexão desta requisição; USER_SESSION sobrevive a commits."""
    try:
        id_usuario = descobre_id_usuario()
        cursor = con.cursor()
        try:
            cursor.execute(
                "SELECT RDB$SET_CONTEXT('USER_SESSION', 'ARKHE_ID_USUARIO', ?) FROM RDB$DATABASE",
                (str(id_usuario) if id_usuario else None,),
            )
            cursor.fetchone()
            cursor.execute(
                "SELECT RDB$SET_CONTEXT('USER_SESSION', 'ARKHE_ORIGEM', ?) FROM RDB$DATABASE",
                (_rota_log(),),
            )
            cursor.fetchone()
            con.commit()
        finally:
            cursor.close()
    except Exception:
        # A instrumentação não deve impedir uma operação bancária preexistente.
        try:
            current_app.logger.exception('Não foi possível definir o contexto de auditoria Firebird')
        except RuntimeError:
            pass


def _rota_log():
    # A rota parametrizada evita copiar tokens e dados pessoais presentes na URL.
    if request.url_rule:
        return request.url_rule.rule[:160]
    return '/rota-nao-encontrada'


def _registrar_resposta_relevante(response):
    caminho = request.path or ''
    assistente = caminho.startswith('/api/v1/assistente/') or caminho == '/api/v1/admin/banco/assistente'
    login = caminho in ('/login', '/login_usuario')
    escrita_recusada = request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and response.status_code >= 400
    login_recusado = login and response.status_code >= 400
    # O próprio feed não produz eventos a cada atualização automática.
    if request.method == 'OPTIONS' or caminho.startswith('/static/') or (
        caminho in ('/api/v1/admin/auditoria', '/api/v1/admin/auditoria/status', '/api/v1/admin/auditoria/stream')
        and response.status_code < 400
    ):
        return response
    contexto = getattr(g, 'auditoria_contexto', {})
    id_usuario = contexto.get('id_usuario') if contexto else descobre_id_usuario()
    id_conta = contexto.get('id_conta') if contexto else descobre_id_conta()
    canal = contexto.get('origem', 'api' if caminho.startswith('/api/v1/') else 'sistema')
    if not (id_usuario or contexto or assistente or login or escrita_recusada or caminho.startswith(('/api/v1/', '/internal/whatsapp/'))):
        return response
    try:
        if login and not id_usuario:
            cpf = (request.get_json(silent=True) or {}).get('cpf')
            if cpf:
                cursor = con.cursor()
                try:
                    cursor.execute('SELECT ID_USUARIO FROM USUARIO WHERE CPF = ?', (str(cpf),))
                    usuario = cursor.fetchone()
                    id_usuario = int(usuario[0]) if usuario else None
                finally:
                    cursor.close()
        resultado = 'SUCESSO' if response.status_code < 400 else 'FALHA' if response.status_code >= 500 else 'RECUSADO'
        motivo = f'Requisição HTTP {response.status_code}'
        if assistente:
            evento = 'MAURO_REQUISICAO'
            motivo = f'Requisição do assistente (HTTP {response.status_code})'
        elif login:
            cookie_autenticacao = any(cookie.startswith('access_token=') for cookie in response.headers.getlist('Set-Cookie'))
            evento = ('TENTATIVA_LOGIN_RECUSADA' if login_recusado else
                      'LOGIN_REALIZADO' if cookie_autenticacao else 'LOGIN_DESAFIO_INICIADO')
            motivo = (f'Autenticação recusada (HTTP {response.status_code})' if login_recusado else
                      'Sessão autenticada' if cookie_autenticacao else 'Etapa de autenticação iniciada')
            resultado = 'RECUSADO' if login_recusado else 'SUCESSO' if cookie_autenticacao else 'PENDENTE'
        else:
            evento = 'OPERACAO_RECUSADA' if escrita_recusada else 'SISTEMA_REQUISICAO'
        dados = {'metodo': request.method, 'status_http': response.status_code,
                 'canal': canal, 'recurso': request.endpoint,
                 'ids': {k:v for k,v in (request.view_args or {}).items() if isinstance(v, int)}}
        if contexto.get('id_integracao'):
            dados['id_integracao'] = contexto['id_integracao']
        registrar_evento_flask(
            evento=evento, resultado=resultado, motivo=motivo,
            id_usuario=id_usuario, id_conta=id_conta,
            operacao='DENY' if response.status_code >= 400 else {'POST':'INSERT', 'PUT':'UPDATE', 'PATCH':'UPDATE', 'DELETE':'DELETE'}.get(request.method, 'READ'),
            origem=_rota_log(), dados=dados,
        )
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and response.status_code < 400:
            try:
                cliente = _redis()
                cliente.publish(CANAL_AUDITORIA, json.dumps({'origem': _rota_log()}))
                cliente.close()
            except Exception:
                pass  # O feed também consulta o arquivo periodicamente.
    except Exception:
        current_app.logger.exception('Falha ao registrar evento HTTP')
        # Escritas já confirmadas mantêm a resposta; o log financeiro é transacional.
        if request.method == 'GET' and response.status_code < 400:
            return current_app.make_response((jsonify({'mensagem': 'Não foi possível registrar o log da operação.'}), 503))
    return response


def _linha_para_json(row):
    return {
        'id_evento': int(row[0]), 'evento': row[1], 'tabela_origem': row[2],
        'operacao': row[3], 'id_registro': int(row[4]) if row[4] is not None else None,
        'id_usuario': int(row[5]) if row[5] is not None else None,
        'id_conta': int(row[6]) if row[6] is not None else None,
        'valor': float(row[7]) if row[7] is not None else None,
        'resultado': row[8], 'motivo': row[9], 'origem': row[10],
        'dados_anteriores': _json_data(row[11]), 'dados_novos': _json_data(row[12]),
        'criado_em': _json_timestamp(row[13]),
    }


def _cadastro_essencial(cursor, id_usuario):
    cursor.execute('SELECT NOME, EMAIL, CPF, CNPJ, TIPO FROM USUARIO WHERE ID_USUARIO = ?', (id_usuario,))
    usuario = cursor.fetchone()
    if not usuario:
        return None
    return {
        'id_usuario': int(id_usuario), 'nome': usuario[0],
        'email': _mascarar_email(usuario[1]),
        'cpf_final': str(usuario[2])[-4:] if usuario[2] else None,
        'cnpj_final': str(usuario[3])[-4:] if usuario[3] else None,
        'tipo': usuario[4],
    }


def _conta_essencial(cursor, id_conta):
    cursor.execute(
        '''SELECT TIPO_CONTA, NUMERO_CONTA, AGENCIA, NOME_FANTASIA, RAZAO_SOCIAL
           FROM CONTA WHERE ID_CONTA = ?''',
        (id_conta,),
    )
    conta = cursor.fetchone()
    if not conta:
        return None
    numero = str(conta[1] or '')
    return {
        'id_conta': int(id_conta), 'tipo': 'PJ' if int(conta[0]) == 1 else 'PF',
        'numero_final': numero[-4:] if numero else None,
        'agencia': conta[2], 'titular': conta[3] or conta[4],
    }


def listar_eventos_admin():
    _, erro = _admin()
    if erro:
        return erro
    filtros = request.args
    try:
        usuario = _id_or_none(filtros.get('usuario_id'))
        conta = _id_or_none(filtros.get('conta_id'))
        inicio = _data_or_none(filtros.get('data_inicio'))
        fim = _data_or_none(filtros.get('data_fim'), fim=True)
        if inicio and fim and inicio > fim:
            raise ValueError('Data inicial posterior à data final')
        minimo = float(filtros['valor_min']) if filtros.get('valor_min') else None
        maximo = float(filtros['valor_max']) if filtros.get('valor_max') else None
        if (minimo is not None and (not math.isfinite(minimo) or minimo < 0)
                or maximo is not None and (not math.isfinite(maximo) or maximo < 0)):
            raise ValueError('O valor do filtro não pode ser negativo')
        if minimo is not None and maximo is not None and minimo > maximo:
            raise ValueError('Valor mínimo maior que valor máximo')
        limite = max(1, min(int(filtros.get('limite', '100')), 200))
    except (ValueError, TypeError) as erro_filtro:
        return jsonify({'mensagem': str(erro_filtro)}), 400

    where, params = [], []
    for campo, valor in (
        ('EVENTO', filtros.get('evento', '').strip()),
        ('RESULTADO', filtros.get('resultado', '').strip()),
    ):
        if valor:
            where.append(f'{campo} = ?')
            params.append(valor[:48])
    if filtros.get('origem'):
        where.append('ORIGEM CONTAINING ?')
        params.append(filtros.get('origem', '').strip()[:160])
    for campo, valor in (('ID_USUARIO', usuario), ('ID_CONTA', conta)):
        if valor is not None:
            where.append(f'{campo} = ?')
            params.append(valor)
    if inicio:
        where.append('CRIADO_EM >= ?')
        params.append(inicio)
    if fim:
        where.append('CRIADO_EM <= ?')
        params.append(fim)
    if minimo is not None:
        where.append('VALOR >= ?')
        params.append(minimo)
    if maximo is not None:
        where.append('VALOR <= ?')
        params.append(maximo)

    conexao = cursor = None
    try:
        conexao = _conectar_banco_auditoria()
        cursor = conexao.cursor()
        cursor.execute(
            f'''SELECT FIRST {limite} ID_AUDITORIA, EVENTO, TABELA_ORIGEM,
                       OPERACAO, ID_REGISTRO, ID_USUARIO, ID_CONTA, VALOR,
                       RESULTADO, MOTIVO, ORIGEM, DADOS_ANTERIORES, DADOS_NOVOS, CRIADO_EM
                FROM AUDITORIA_EVENTO
                {('WHERE ' + ' AND '.join(where)) if where else ''}
                ORDER BY CRIADO_EM DESC, ID_AUDITORIA DESC''',
            tuple(params),
        )
        eventos = [_linha_para_json(row) for row in cursor.fetchall()]
        return jsonify({'eventos': eventos, 'fonte': 'Firebird de auditoria', 'limite': limite}), 200
    except RuntimeError as erro_config:
        return jsonify({'mensagem': str(erro_config)}), 503
    except Exception:
        current_app.logger.exception('Falha ao consultar o banco de auditoria independente')
        return jsonify({'mensagem': 'Central de auditoria indisponível; verifique o banco independente.'}), 503
    finally:
        if cursor:
            cursor.close()
        if conexao:
            conexao.close()


def detalhe_evento_admin(id_evento):
    admin_id, erro = _admin()
    if erro:
        return erro
    conexao = cursor = None
    try:
        conexao = _conectar_banco_auditoria()
        cursor = conexao.cursor()
        cursor.execute(
            '''SELECT ID_AUDITORIA, EVENTO, TABELA_ORIGEM, OPERACAO,
                      ID_REGISTRO, ID_USUARIO, ID_CONTA, VALOR, RESULTADO,
                      MOTIVO, ORIGEM, DADOS_ANTERIORES, DADOS_NOVOS, CRIADO_EM
               FROM AUDITORIA_EVENTO WHERE ID_AUDITORIA = ?''',
            (int(id_evento),),
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({'mensagem': 'Evento não encontrado'}), 404
        evento = _linha_para_json(row)
        _registrar_acesso_detalhe(admin_id, 'evento_auditoria', id_evento)
        cursor.close()
        cursor = con.cursor()
        evento['cadastro'] = _cadastro_essencial(cursor, evento['id_usuario']) if evento['id_usuario'] else None
        snapshots = (evento['dados_anteriores'], evento['dados_novos'])
        ids_usuarios = set()
        ids_contas = {evento['id_conta']} if evento['id_conta'] else set()
        for snapshot in snapshots:
            if not isinstance(snapshot, dict):
                continue
            for chave in ('id_usuario', 'id_usuario_alvo'):
                try:
                    valor_usuario = int(snapshot.get(chave) or 0)
                    if valor_usuario > 0 and valor_usuario != evento['id_usuario']:
                        ids_usuarios.add(valor_usuario)
                except (TypeError, ValueError):
                    pass
            for chave in ('id_conta', 'id_pagador', 'id_recebedor', 'id_conta_destino'):
                try:
                    valor_conta = int(snapshot.get(chave) or 0)
                    if valor_conta > 0:
                        ids_contas.add(valor_conta)
                except (TypeError, ValueError):
                    pass
        evento['usuarios_envolvidos'] = [cadastro for cadastro in
            (_cadastro_essencial(cursor, id_usuario) for id_usuario in sorted(ids_usuarios)) if cadastro]
        evento['contas_envolvidas'] = [conta for conta in
            (_conta_essencial(cursor, id_conta) for id_conta in sorted(ids_contas)) if conta]
        evento['conta'] = next((item for item in evento['contas_envolvidas'] if item['id_conta'] == evento['id_conta']), None)
        return jsonify({'evento': evento}), 200
    except RuntimeError as erro_config:
        return jsonify({'mensagem': str(erro_config)}), 503
    except Exception:
        current_app.logger.exception('Falha ao carregar detalhe de auditoria')
        return jsonify({'mensagem': 'Não foi possível carregar o evento de auditoria.'}), 503
    finally:
        if cursor:
            cursor.close()
        if conexao:
            conexao.close()


def _mascarar_email(valor):
    email = str(valor or '')
    if '@' not in email:
        return None
    parte, dominio = email.split('@', 1)
    return (parte[:1] + '***@' + dominio) if parte else '***@' + dominio


def status_auditoria_admin():
    _, erro = _admin()
    if erro:
        return erro
    banco = redis_status = False
    try:
        conexao = _conectar_banco_auditoria()
        cursor = conexao.cursor()
        cursor.execute('SELECT COUNT(*) FROM AUDITORIA_EVENTO')
        total = int(cursor.fetchone()[0])
        cursor.close()
        conexao.close()
        banco = True
    except Exception as erro_db:
        total = None
        detalhe_db = str(erro_db)
    try:
        cliente = _redis()
        redis_status = bool(cliente.ping())
        cliente.close()
    except Exception:
        redis_status = False
    return jsonify({
        'banco_auditoria': 'conectado' if banco else 'indisponivel',
        'redis': 'conectado' if redis_status else 'indisponivel',
        'eventos_persistidos': total,
        'fonte_persistente': 'Firebird independente',
        **({'detalhe_banco': detalhe_db[:250]} if not banco else {}),
    }), 200 if banco else 503


def stream_eventos_admin():
    _, erro = _admin()
    if erro:
        return erro
    try:
        cliente = _redis()
        cliente.ping()
        pubsub = cliente.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(CANAL_AUDITORIA)
    except Exception:
        return jsonify({'mensagem': 'Redis indisponível para atualização ao vivo.'}), 503

    @stream_with_context
    def transmitir():
        try:
            yield 'event: pronto\ndata: {}\n\n'
            while True:
                mensagem = pubsub.get_message(timeout=15)
                if mensagem and mensagem.get('type') == 'message':
                    yield f"event: auditoria\ndata: {mensagem.get('data', '{}')}\n\n"
                else:
                    yield ': keep-alive\n\n'
                time.sleep(0.1)
        except GeneratorExit:
            raise
        finally:
            pubsub.close()
            cliente.close()

    return Response(
        transmitir(), mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache, no-transform', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'},
    )


def processar_evento_pendente(id_evento):
    """Entrega idempotente: Firebird separado primeiro, sinal Redis depois."""
    cursor = None
    token = str(uuid.uuid4())
    conexao_auditoria = None
    try:
        cursor = con.cursor()
        cursor.execute(
            f'''UPDATE AUDITORIA_EVENTO_OUTBOX
               SET BLOQUEIO_TOKEN = ?, BLOQUEIO_ATE = DATEADD({LEASE_SEGUNDOS} SECOND TO CURRENT_TIMESTAMP),
                   TENTATIVAS = TENTATIVAS + 1
               WHERE ID_EVENTO = ? AND PROXIMA_TENTATIVA <= CURRENT_TIMESTAMP
                 AND (BLOQUEIO_ATE IS NULL OR BLOQUEIO_ATE < CURRENT_TIMESTAMP)
                 AND (AUDITADO_EM IS NULL OR PUBLICADO_EM IS NULL)
               RETURNING ID_EVENTO, EVENTO, TABELA_ORIGEM, OPERACAO, ID_REGISTRO,
                         ID_USUARIO, ID_CONTA, VALOR, RESULTADO, MOTIVO, ORIGEM,
                         DADOS_ANTERIORES, DADOS_NOVOS, CRIADO_EM, AUDITADO_EM, PUBLICADO_EM''',
            (token, int(id_evento)),
        )
        row = cursor.fetchone()
        if not row:
            con.rollback()
            return False
        con.commit()

        if row[14] is None:
            conexao_auditoria = _conectar_banco_auditoria()
            cursor_auditoria = conexao_auditoria.cursor()
            origem_id = _origem_id()
            cursor_auditoria.execute(
                'SELECT ID_AUDITORIA FROM AUDITORIA_EVENTO WHERE ORIGEM_ID = ? AND ID_EVENTO_ORIGEM = ?',
                (origem_id, int(row[0])),
            )
            existe = cursor_auditoria.fetchone()
            if not existe:
                cursor_auditoria.execute(
                    '''INSERT INTO AUDITORIA_EVENTO
                       (ORIGEM_ID, ID_EVENTO_ORIGEM, EVENTO, TABELA_ORIGEM, OPERACAO,
                        ID_REGISTRO, ID_USUARIO, ID_CONTA, VALOR, RESULTADO, MOTIVO,
                        ORIGEM, DADOS_ANTERIORES, DADOS_NOVOS, CRIADO_EM)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (origem_id, int(row[0]), *row[1:14]),
                )
            conexao_auditoria.commit()
            cursor_auditoria.close()

            cursor.execute(
                '''UPDATE AUDITORIA_EVENTO_OUTBOX SET AUDITADO_EM = CURRENT_TIMESTAMP,
                          ERRO_ULTIMO = NULL
                   WHERE ID_EVENTO = ? AND BLOQUEIO_TOKEN = ?''',
                (int(row[0]), token),
            )
            con.commit()

        if row[15] is None:
            cliente = _redis()
            cliente.publish(CANAL_AUDITORIA, json.dumps({
                'id_evento': int(row[0]), 'evento': row[1], 'criado_em': _json_timestamp(row[13]),
            }, separators=(',', ':')))
            cliente.close()
            cursor.execute(
                '''UPDATE AUDITORIA_EVENTO_OUTBOX SET PUBLICADO_EM = CURRENT_TIMESTAMP,
                          BLOQUEIO_TOKEN = NULL, BLOQUEIO_ATE = NULL, ERRO_ULTIMO = NULL
                   WHERE ID_EVENTO = ? AND BLOQUEIO_TOKEN = ?''',
                (int(row[0]), token),
            )
            con.commit()
        else:
            cursor.execute(
                '''UPDATE AUDITORIA_EVENTO_OUTBOX SET BLOQUEIO_TOKEN = NULL, BLOQUEIO_ATE = NULL
                   WHERE ID_EVENTO = ? AND BLOQUEIO_TOKEN = ?''',
                (int(row[0]), token),
            )
            con.commit()
        return True
    except Exception as erro:
        try:
            con.rollback()
            if cursor:
                cursor.execute(
                    '''UPDATE AUDITORIA_EVENTO_OUTBOX
                       SET PROXIMA_TENTATIVA = DATEADD(30 SECOND TO CURRENT_TIMESTAMP),
                           BLOQUEIO_TOKEN = NULL, BLOQUEIO_ATE = NULL, ERRO_ULTIMO = ?
                       WHERE ID_EVENTO = ? AND BLOQUEIO_TOKEN = ?''',
                    (str(erro)[:500], int(id_evento), token),
                )
                con.commit()
        except Exception:
            con.rollback()
        current_app.logger.warning('Evento de auditoria %s ficou pendente: %s', id_evento, erro)
        return False
    finally:
        if cursor:
            cursor.close()
        if conexao_auditoria:
            conexao_auditoria.close()


def processar_auditoria_pendente(limite=100):
    global _ULTIMO_AVISO_SCHEMA
    limite = max(1, min(int(limite), 500))
    cursor = con.cursor()
    try:
        try:
            cursor.execute(
                f'''SELECT FIRST {limite} ID_EVENTO FROM AUDITORIA_EVENTO_OUTBOX
                    WHERE (AUDITADO_EM IS NULL OR PUBLICADO_EM IS NULL)
                      AND PROXIMA_TENTATIVA <= CURRENT_TIMESTAMP
                      AND (BLOQUEIO_ATE IS NULL OR BLOQUEIO_ATE < CURRENT_TIMESTAMP)
                    ORDER BY ID_EVENTO'''
            )
            ids = [int(row[0]) for row in cursor.fetchall()]
        except Exception as erro_schema:
            try:
                con.rollback()
            except Exception:
                pass
            agora = time.monotonic()
            if agora - _ULTIMO_AVISO_SCHEMA >= 60:
                current_app.logger.warning('Outbox de auditoria ainda não está instalado no Firebird principal: %s', erro_schema)
                _ULTIMO_AVISO_SCHEMA = agora
            return 0
    finally:
        cursor.close()
    return sum(1 for id_evento in ids if processar_evento_pendente(id_evento))


def registrar_rotas(app):
    app.before_request(_preparar_contexto_trigger)
    app.after_request(_registrar_resposta_relevante)
    app.add_url_rule('/api/v1/admin/auditoria', 'listar_eventos_auditoria_admin', listar_eventos_admin, methods=['GET'])
    app.add_url_rule('/api/v1/admin/auditoria/<int:id_evento>', 'detalhe_evento_auditoria_admin', detalhe_evento_admin, methods=['GET'])
    app.add_url_rule('/api/v1/admin/auditoria/status', 'status_auditoria_admin', status_auditoria_admin, methods=['GET'])
    app.add_url_rule('/api/v1/admin/auditoria/stream', 'stream_eventos_auditoria_admin', stream_eventos_admin, methods=['GET'])
