"""Favoritos Pix isolados por conta ativa e usuário autenticado."""
import hashlib

from flask import jsonify, request

from banco import con
from funcao import descobre_id_conta, descobre_id_usuario, usuario_pode_acessar_conta
from main import app


CAMPOS_CHAVE = {
    'cpf': 'CHAVE_PIX_CPF',
    'cnpj': 'CHAVE_PIX_CNPJ',
    'email': 'CHAVE_PIX_EMAIL',
    'telefone': 'CHAVE_PIX_TELEFONE',
    'aleatoria': 'CHAVE_PIX_ALEATORIA',
}


def _contexto():
    id_usuario = descobre_id_usuario()
    id_conta = descobre_id_conta()
    if not id_usuario or not id_conta:
        return None, (jsonify({'mensagem': 'Sessão inválida ou conta não selecionada'}), 401)
    try:
        if not usuario_pode_acessar_conta(id_usuario, id_conta):
            return None, (jsonify({'mensagem': 'Usuário sem acesso ativo a esta conta'}), 403)
    except Exception:
        app.logger.exception('Falha ao validar acesso a favoritos Pix')
        return None, (jsonify({'mensagem': 'Não foi possível validar o acesso à conta'}), 503)
    return {'id_usuario': int(id_usuario), 'id_conta': int(id_conta)}, None


def _normalizar_chave(tipo, valor):
    if tipo not in CAMPOS_CHAVE or not isinstance(valor, str):
        return None
    chave = valor.strip()
    if tipo in ('cpf', 'cnpj', 'telefone'):
        chave = ''.join(caractere for caractere in chave if caractere.isdigit())
    if not 1 <= len(chave) <= 160:
        return None
    return chave


def _resolver_destinatario(cursor, tipo, chave):
    cursor.execute(
        '''SELECT FIRST 2 C.ID_CONTA, C.TIPO_CONTA, U.NOME,
                  C.NOME_FANTASIA, C.RAZAO_SOCIAL
           FROM CHAVE_PIX K
           INNER JOIN CONTA C ON C.ID_CONTA = K.ID_CONTA
           INNER JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
           WHERE K.''' + CAMPOS_CHAVE[tipo] + ' = ?', (chave,)
    )
    encontrados = cursor.fetchall()
    if len(encontrados) != 1:
        return None
    destino = encontrados[0]
    nome = (destino[3] or destino[4] or destino[2]) if int(destino[1]) == 1 else destino[2]
    return {'id_conta': int(destino[0]), 'nome': str(nome or 'Destinatário Arkhé')}


@app.route('/favoritos_pix', methods=['GET'])
def listar_favoritos_pix():
    contexto, erro = _contexto()
    if erro:
        return erro
    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute(
            '''SELECT ID_FAVORITO, TIPO_CHAVE, CHAVE_PIX, ROTULO,
                      NOME_DESTINATARIO, ID_CONTA_DESTINO, CRIADO_EM
               FROM FAVORITO_PIX
               WHERE ID_CONTA = ? AND ID_USUARIO = ? AND ATIVO = 1
               ORDER BY ROTULO, ID_FAVORITO''',
            (contexto['id_conta'], contexto['id_usuario'])
        )
        favoritos = [{
            'id': linha[0], 'tipo_chave': linha[1], 'chave_pix': linha[2],
            'rotulo': linha[3], 'nome_destinatario': linha[4],
            'id_conta_destino': linha[5],
            'criado_em': linha[6].isoformat() if linha[6] else None,
        } for linha in cursor.fetchall()]
        return jsonify({'favoritos': favoritos}), 200
    except Exception:
        app.logger.exception('Falha ao listar favoritos Pix')
        return jsonify({'mensagem': 'Não foi possível carregar os favoritos'}), 500
    finally:
        if cursor:
            cursor.close()


@app.route('/favoritos_pix', methods=['POST'])
def salvar_favorito_pix():
    contexto, erro = _contexto()
    if erro:
        return erro
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return jsonify({'mensagem': 'Envie os dados do favorito em JSON'}), 400
    tipo = str(dados.get('tipo_chave') or '').strip().lower()
    chave = _normalizar_chave(tipo, dados.get('chave_pix'))
    rotulo = str(dados.get('rotulo') or '').strip()
    if not chave:
        return jsonify({'mensagem': 'Informe um tipo e uma chave Pix válidos'}), 400
    if not 1 <= len(rotulo) <= 100:
        return jsonify({'mensagem': 'O nome do favorito deve ter de 1 a 100 caracteres'}), 400
    chave_hash = hashlib.sha256(f'{tipo}\0{chave}'.encode('utf-8')).hexdigest()

    cursor = None
    try:
        cursor = con.cursor()
        destino = _resolver_destinatario(cursor, tipo, chave)
        if not destino:
            con.rollback()
            return jsonify({'mensagem': 'Chave Pix não encontrada ou ambígua'}), 404
        if destino['id_conta'] == contexto['id_conta']:
            con.rollback()
            return jsonify({'mensagem': 'Não é possível favoritar uma chave da própria conta'}), 400

        cursor.execute(
            '''SELECT ID_FAVORITO FROM FAVORITO_PIX
               WHERE ID_CONTA = ? AND ID_USUARIO = ? AND TIPO_CHAVE = ? AND CHAVE_HASH = ?''',
            (contexto['id_conta'], contexto['id_usuario'], tipo, chave_hash)
        )
        existente = cursor.fetchone()
        if existente:
            cursor.execute(
                '''UPDATE FAVORITO_PIX
                   SET ID_CONTA_DESTINO = ?, ROTULO = ?, NOME_DESTINATARIO = ?,
                       ATIVO = 1, ATUALIZADO_EM = CURRENT_TIMESTAMP
                   WHERE ID_FAVORITO = ? AND ID_CONTA = ? AND ID_USUARIO = ?''',
                (destino['id_conta'], rotulo, destino['nome'], existente[0],
                 contexto['id_conta'], contexto['id_usuario'])
            )
            id_favorito = int(existente[0])
        else:
            cursor.execute(
                '''INSERT INTO FAVORITO_PIX
                   (ID_CONTA, ID_USUARIO, ID_CONTA_DESTINO, TIPO_CHAVE, CHAVE_PIX,
                    CHAVE_HASH, ROTULO, NOME_DESTINATARIO, ATIVO)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1) RETURNING ID_FAVORITO''',
                (contexto['id_conta'], contexto['id_usuario'], destino['id_conta'],
                 tipo, chave, chave_hash, rotulo, destino['nome'])
            )
            id_favorito = int(cursor.fetchone()[0])
        con.commit()
        return jsonify({
            'mensagem': 'Destinatário salvo nos favoritos',
            'favorito': {'id': id_favorito, 'tipo_chave': tipo,
                         'chave_pix': chave, 'rotulo': rotulo,
                         'nome_destinatario': destino['nome'],
                         'id_conta_destino': destino['id_conta']},
        }), 201
    except Exception:
        con.rollback()
        app.logger.exception('Falha ao salvar favorito Pix')
        return jsonify({'mensagem': 'Não foi possível salvar o favorito'}), 500
    finally:
        if cursor:
            cursor.close()


@app.route('/favoritos_pix/<int:id_favorito>', methods=['DELETE'])
def excluir_favorito_pix(id_favorito):
    contexto, erro = _contexto()
    if erro:
        return erro
    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute(
            '''UPDATE FAVORITO_PIX SET ATIVO = 0, ATUALIZADO_EM = CURRENT_TIMESTAMP
               WHERE ID_FAVORITO = ? AND ID_CONTA = ? AND ID_USUARIO = ? AND ATIVO = 1
               RETURNING ID_FAVORITO''',
            (id_favorito, contexto['id_conta'], contexto['id_usuario'])
        )
        if not cursor.fetchone():
            con.rollback()
            return jsonify({'mensagem': 'Favorito não encontrado'}), 404
        con.commit()
        return jsonify({'mensagem': 'Favorito removido'}), 200
    except Exception:
        con.rollback()
        app.logger.exception('Falha ao remover favorito Pix')
        return jsonify({'mensagem': 'Não foi possível remover o favorito'}), 500
    finally:
        if cursor:
            cursor.close()


def destinatario_esta_favoritado(id_conta, id_usuario, id_conta_destino):
    """A consulta também fica escopada pelo usuário e pela conta em uso."""
    if not id_conta or not id_usuario or not id_conta_destino:
        return False
    if not usuario_pode_acessar_conta(id_usuario, id_conta):
        return False
    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute(
            '''SELECT FIRST 1 ID_FAVORITO FROM FAVORITO_PIX
               WHERE ID_CONTA = ? AND ID_USUARIO = ?
                 AND ID_CONTA_DESTINO = ? AND ATIVO = 1''',
            (int(id_conta), int(id_usuario), int(id_conta_destino))
        )
        return cursor.fetchone() is not None
    finally:
        if cursor:
            cursor.close()


def validar_favorito_selecionado(id_favorito, id_conta, id_usuario,
                                id_conta_destino, tipo, chave):
    """Impede que uma chave alterada/reaproveitada receba a política especial."""
    try:
        id_favorito = int(id_favorito)
    except (TypeError, ValueError):
        return False
    chave_normalizada = _normalizar_chave(tipo, chave)
    if not chave_normalizada or not usuario_pode_acessar_conta(id_usuario, id_conta):
        return False
    chave_hash = hashlib.sha256(f'{tipo}\0{chave_normalizada}'.encode('utf-8')).hexdigest()
    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute(
            '''SELECT FIRST 1 ID_FAVORITO FROM FAVORITO_PIX
               WHERE ID_FAVORITO = ? AND ID_CONTA = ? AND ID_USUARIO = ?
                 AND ID_CONTA_DESTINO = ? AND TIPO_CHAVE = ?
                 AND CHAVE_HASH = ? AND ATIVO = 1''',
            (id_favorito, int(id_conta), int(id_usuario), int(id_conta_destino), tipo, chave_hash)
        )
        return cursor.fetchone() is not None
    finally:
        if cursor:
            cursor.close()
