"""Rotas autenticadas da central persistente de notificacoes."""
import datetime
import json
import re

from flask import jsonify, request

from banco import con
from funcao import descobre_id_conta, descobre_id_usuario, usuario_pode_acessar_conta
from main import app
from notificacoes import (
    CATEGORIAS_CONFIGURAVEIS,
    registrar_evento_seguranca,
    tentar_publicar_evento,
)


def _contexto_autenticado():
    id_usuario = descobre_id_usuario()
    id_conta = descobre_id_conta()
    if not id_usuario:
        return None, (jsonify({'mensagem': 'Autenticacao necessaria'}), 401)

    if id_conta:
        # Revalida a relacao em toda requisicao: titularidade PF/PJ ou acesso PJ
        # ainda ativo. O destinatario continua sendo ID_USUARIO, nunca a conta.
        try:
            if not usuario_pode_acessar_conta(id_usuario, id_conta):
                return None, (jsonify({'mensagem': 'Usuario sem acesso ativo a esta conta'}), 403)
            cursor = con.cursor()
            try:
                cursor.execute(
                    'SELECT ID_USUARIO, TIPO_CONTA FROM CONTA WHERE ID_CONTA = ?',
                    (id_conta,)
                )
                conta = cursor.fetchone()
                if not conta:
                    return None, (jsonify({'mensagem': 'Conta nao encontrada'}), 404)
                if int(conta[0]) != int(id_usuario):
                    cursor.execute(
                        '''SELECT 1 FROM ACESSO_CONTA
                           WHERE ID_CONTA = ? AND ID_USUARIO = ? AND STATUS = 1''',
                        (id_conta, id_usuario)
                    )
                    acesso = cursor.fetchone()
                    if int(conta[1]) != 1 or not acesso:
                        return None, (jsonify({'mensagem': 'Vinculo de acesso PJ inativo ou invalido'}), 403)
            finally:
                cursor.close()
        except Exception:
            app.logger.exception('Falha ao validar acesso a notificacoes')
            return None, (jsonify({'mensagem': 'Nao foi possivel validar o acesso a conta'}), 503)

    return {'id_usuario': int(id_usuario), 'id_conta': int(id_conta) if id_conta else None}, None


def _filtro_escopo(contexto):
    if contexto['id_conta'] is None:
        return "D.ID_CONTA IS NULL AND N.CATEGORIA = 'SEGURANCA_CRITICA'", ()
    return (
        "((D.ID_CONTA = ?) OR (D.ID_CONTA IS NULL AND N.CATEGORIA = 'SEGURANCA_CRITICA'))",
        (contexto['id_conta'],)
    )


def _data_json(valor):
    return valor.isoformat() if hasattr(valor, 'isoformat') else (str(valor) if valor is not None else None)


@app.route('/api/v1/notificacoes', methods=['GET'])
def listar_notificacoes():
    contexto, erro = _contexto_autenticado()
    if erro:
        return erro
    try:
        limite = int(request.args.get('limite', '50'))
        deslocamento = int(request.args.get('deslocamento', '0'))
    except (TypeError, ValueError):
        return jsonify({'mensagem': 'limite e deslocamento devem ser inteiros'}), 400
    if not 1 <= limite <= 100 or not 0 <= deslocamento <= 5000:
        return jsonify({'mensagem': 'Use limite entre 1 e 100 e deslocamento entre 0 e 5000'}), 400

    escopo_sql, escopo_params = _filtro_escopo(contexto)
    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute(
            f'''SELECT FIRST {limite} SKIP {deslocamento}
                       N.ID_NOTIFICACAO, N.CATEGORIA, N.TITULO, N.MENSAGEM,
                       N.DADOS_JSON, D.LIDA_EM, D.SUPRIMIDA_EM, N.CRIADO_EM,
                       N.ID_CONTA, N.ID_USUARIO_DESTINO
                FROM NOTIFICACAO_DESTINATARIO D
                INNER JOIN NOTIFICACAO N ON N.ID_NOTIFICACAO = D.ID_NOTIFICACAO
                LEFT JOIN PREFERENCIA_NOTIFICACAO P
                  ON P.ID_USUARIO = D.ID_USUARIO AND P.CATEGORIA = N.CATEGORIA
                WHERE D.ID_USUARIO = ? AND {escopo_sql}
                  AND (N.CATEGORIA = 'SEGURANCA_CRITICA' OR COALESCE(P.ATIVO, 1) = 1)
                ORDER BY N.CRIADO_EM DESC, N.ID_NOTIFICACAO DESC''',
            (contexto['id_usuario'],) + escopo_params
        )
        resultado = []
        for row in cursor.fetchall():
            lida = row[5] is not None
            suprimida = row[6] is not None
            try:
                dados_notificacao = json.loads(row[4]) if row[4] else {}
            except (TypeError, ValueError):
                dados_notificacao = {}
            resultado.append({
                'id': int(row[0]),
                'categoria': row[1],
                'titulo': row[2],
                'mensagem': row[3],
                'dados': dados_notificacao,
                'lida': lida,
                'suprimida_por_preferencia': suprimida,
                'elegivel_para_nao_lidas': not lida and not suprimida,
                'estado_leitura': 'lida' if lida else ('suprimida' if suprimida else 'nao_lida'),
                'criada_em': _data_json(row[7]),
                'id_conta': row[8],
                'pessoal': row[8] is None,
            })
        return jsonify({'notificacoes': resultado, 'limite': limite, 'deslocamento': deslocamento}), 200
    except Exception:
        app.logger.exception('Falha ao listar notificacoes')
        return jsonify({'mensagem': 'Nao foi possivel listar notificacoes'}), 500
    finally:
        if cursor:
            cursor.close()


@app.route('/api/v1/notificacoes/contador', methods=['GET'])
def contador_notificacoes():
    contexto, erro = _contexto_autenticado()
    if erro:
        return erro
    escopo_sql, escopo_params = _filtro_escopo(contexto)
    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute(
            f'''SELECT COUNT(*)
                FROM NOTIFICACAO_DESTINATARIO D
                INNER JOIN NOTIFICACAO N ON N.ID_NOTIFICACAO = D.ID_NOTIFICACAO
                LEFT JOIN PREFERENCIA_NOTIFICACAO P
                  ON P.ID_USUARIO = D.ID_USUARIO AND P.CATEGORIA = N.CATEGORIA
                WHERE D.ID_USUARIO = ? AND {escopo_sql}
                  AND D.LIDA_EM IS NULL AND D.SUPRIMIDA_EM IS NULL
                  AND (N.CATEGORIA = 'SEGURANCA_CRITICA' OR COALESCE(P.ATIVO, 1) = 1)''',
            (contexto['id_usuario'],) + escopo_params
        )
        return jsonify({'nao_lidas': int(cursor.fetchone()[0] or 0)}), 200
    except Exception:
        app.logger.exception('Falha ao consultar contador de notificacoes')
        return jsonify({'mensagem': 'Nao foi possivel consultar o contador'}), 500
    finally:
        if cursor:
            cursor.close()


@app.route('/api/v1/notificacoes/<int:id_notificacao>/lida', methods=['PATCH'])
def marcar_notificacao_lida(id_notificacao):
    contexto, erro = _contexto_autenticado()
    if erro:
        return erro
    if contexto['id_conta'] is None:
        escopo_sql, escopo_params = 'D.ID_CONTA IS NULL', ()
    else:
        # A identidade do destinatario protege avisos pessoais; o NULL e reservado
        # a avisos de seguranca da propria pessoa, nunca aos demais membros da PJ.
        escopo_sql, escopo_params = '(D.ID_CONTA = ? OR D.ID_CONTA IS NULL)', (contexto['id_conta'],)
    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute(
            f'''UPDATE NOTIFICACAO_DESTINATARIO D
                SET LIDA_EM = COALESCE(LIDA_EM, CURRENT_TIMESTAMP)
                WHERE D.ID_NOTIFICACAO = ? AND D.ID_USUARIO = ?
                  AND {escopo_sql}
                RETURNING ID_DESTINATARIO''',
            (id_notificacao, contexto['id_usuario']) + escopo_params
        )
        atualizado = cursor.fetchone()
        if not atualizado:
            con.rollback()
            return jsonify({'mensagem': 'Notificacao nao encontrada'}), 404
        con.commit()
        return jsonify({'id': id_notificacao, 'lida': True}), 200
    except Exception:
        con.rollback()
        app.logger.exception('Falha ao marcar notificacao como lida')
        return jsonify({'mensagem': 'Nao foi possivel atualizar a notificacao'}), 500
    finally:
        if cursor:
            cursor.close()


@app.route('/api/v1/notificacoes/preferencias', methods=['GET'])
def obter_preferencias_notificacao():
    contexto, erro = _contexto_autenticado()
    if erro:
        return erro
    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute(
            'SELECT CATEGORIA, ATIVO FROM PREFERENCIA_NOTIFICACAO WHERE ID_USUARIO = ?',
            (contexto['id_usuario'],)
        )
        definidas = {str(row[0]): int(row[1]) == 1 for row in cursor.fetchall()}
        return jsonify({
            'preferencias': [
                {'categoria': categoria, 'ativo': definidas.get(categoria, True), 'obrigatoria': False}
                for categoria in CATEGORIAS_CONFIGURAVEIS
            ] + [{'categoria': 'SEGURANCA_CRITICA', 'ativo': True, 'obrigatoria': True}]
        }), 200
    except Exception:
        app.logger.exception('Falha ao consultar preferencias de notificacao')
        return jsonify({'mensagem': 'Nao foi possivel consultar preferencias'}), 500
    finally:
        if cursor:
            cursor.close()


@app.route('/api/v1/notificacoes/preferencias', methods=['PUT'])
def atualizar_preferencias_notificacao():
    contexto, erro = _contexto_autenticado()
    if erro:
        return erro
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict) or not dados or any(
        categoria not in CATEGORIAS_CONFIGURAVEIS or type(ativo) is not bool
        for categoria, ativo in dados.items()
    ):
        return jsonify({
            'mensagem': 'Envie um objeto categoria:boolean para PIX, TRANSFERENCIA, BOLETO, CARTAO ou INFORMATIVO'
        }), 400

    cursor = None
    try:
        cursor = con.cursor()
        for categoria, ativo in dados.items():
            valor = int(ativo)
            cursor.execute(
                '''UPDATE OR INSERT INTO PREFERENCIA_NOTIFICACAO
                   (ID_USUARIO, CATEGORIA, ATIVO, ATUALIZADO_EM)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                   MATCHING (ID_USUARIO, CATEGORIA)''',
                (contexto['id_usuario'], categoria, valor)
            )
            if not ativo:
                cursor.execute(
                    '''UPDATE NOTIFICACAO_DESTINATARIO D
                       SET SUPRIMIDA_EM = CURRENT_TIMESTAMP
                       WHERE D.ID_USUARIO = ? AND D.LIDA_EM IS NULL AND D.SUPRIMIDA_EM IS NULL
                         AND D.ID_NOTIFICACAO IN (
                           SELECT N.ID_NOTIFICACAO FROM NOTIFICACAO N
                           WHERE N.CATEGORIA = ? AND N.CATEGORIA <> 'SEGURANCA_CRITICA'
                         )''',
                    (contexto['id_usuario'], categoria)
                )
                cursor.execute(
                    '''UPDATE EVENTO_NOTIFICACAO_OUTBOX E SET PUBLICAR = 0
                       WHERE E.ID_EVENTO IN (
                         SELECT N.ID_EVENTO FROM NOTIFICACAO N
                         WHERE N.ID_USUARIO_DESTINO = ? AND N.CATEGORIA = ?
                       ) AND E.PUBLICADO_EM IS NULL''',
                    (contexto['id_usuario'], categoria)
                )
        con.commit()
        return jsonify({'mensagem': 'Preferencias atualizadas', 'preferencias': dados}), 200
    except Exception:
        con.rollback()
        app.logger.exception('Falha ao atualizar preferencias de notificacao')
        return jsonify({'mensagem': 'Nao foi possivel atualizar preferencias'}), 500
    finally:
        if cursor:
            cursor.close()


@app.after_request
def notificar_bloqueio_login(response):
    """Registra alerta critico sem alterar a implementacao existente de login."""
    if request.path not in ('/login', '/login_usuario') or response.status_code != 429:
        return response
    try:
        corpo = response.get_json(silent=True)
        if not isinstance(corpo, dict):
            return response
        if 'Acesso bloqueado temporariamente' not in str(corpo.get('mensagem') or ''):
            return response
        dados = request.get_json(silent=True)
        if not isinstance(dados, dict):
            return response
        cpf = re.sub(r'\D', '', str(dados.get('cpf') or ''))
        if len(cpf) != 11:
            return response

        cursor = con.cursor()
        try:
            cursor.execute(
                "SELECT ID_USUARIO FROM USUARIO WHERE REPLACE(REPLACE(CPF, '.', ''), '-', '') = ?",
                (cpf,)
            )
            usuario = cursor.fetchone()
            if not usuario:
                return response
            id_usuario = int(usuario[0])
            janela = int(datetime.datetime.now().timestamp() // 900)
            evento = registrar_evento_seguranca(
                cursor,
                chave=f'login-bloqueado:{id_usuario}:{janela}',
                id_usuario=id_usuario,
                titulo='Acesso temporariamente bloqueado',
                mensagem='Detectamos varias tentativas incorretas de acesso. Confira sua seguranca.',
                dados={'tipo': 'tentativas_login'},
                referencia_tipo='LOGIN',
            )
            con.commit()
        finally:
            cursor.close()
        tentar_publicar_evento(evento)
    except Exception:
        try:
            con.rollback()
        except Exception:
            pass
        app.logger.exception('Falha ao persistir notificacao de bloqueio de login')
    return response
