from flask import jsonify, request
from main import app
from banco import con
from funcao import descobre_id_conta
import uuid


def gerar_chave_pix():
    return str(uuid.uuid4())


@app.route('/adicionar_chave_pix', methods=['POST'])
def adicionar_chave_pix():
    dados = request.get_json()

    chave_pix_email = dados.get('chave_pix_email')
    chave_pix_telefone = dados.get('chave_pix_telefone')
    chave_pix_cpf = dados.get('chave_pix_cpf')
    chave_pix_aleatoria = dados.get('chave_pix_aleatoria')
    chave_pix_cnpj = dados.get('chave_pix_cnpj')

    if chave_pix_aleatoria:
        chave_pix_aleatoria = gerar_chave_pix()

    id_conta = descobre_id_conta()

    if id_conta is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    chave_informada = chave_pix_email or chave_pix_telefone or chave_pix_cpf or chave_pix_aleatoria or chave_pix_cnpj

    if not chave_informada:
        return jsonify({'mensagem': 'Informe uma chave Pix'}), 400

    cursor = con.cursor()

    try:
        cursor.execute("SELECT ID_CHAVE_PIX, CHAVE_PIX_EMAIL, CHAVE_PIX_TELEFONE, CHAVE_PIX_CPF, CHAVE_PIX_ALEATORIA, CHAVE_PIX_CNPJ FROM CHAVE_PIX WHERE ID_CONTA = ?", (id_conta,))
        existe_chave_pix = cursor.fetchone()

        if existe_chave_pix:
            if chave_pix_email and existe_chave_pix[1]:
                return jsonify({'mensagem': 'Chave Pix de email ja cadastrada'}), 400

            if chave_pix_telefone and existe_chave_pix[2]:
                return jsonify({'mensagem': 'Chave Pix de telefone ja cadastrada'}), 400

            if chave_pix_cpf and existe_chave_pix[3]:
                return jsonify({'mensagem': 'Chave Pix de CPF ja cadastrada'}), 400

            if chave_pix_aleatoria and existe_chave_pix[4]:
                return jsonify({'mensagem': 'Chave Pix aleatoria ja cadastrada'}), 400

            if chave_pix_cnpj and existe_chave_pix[5]:
                return jsonify({'mensagem': 'Chave Pix de CNPJ ja cadastrada'}), 400

        if chave_pix_email:
            cursor.execute("SELECT ID_CHAVE_PIX FROM CHAVE_PIX WHERE CHAVE_PIX_EMAIL = ?", (chave_pix_email,))
            if cursor.fetchone():
                return jsonify({'mensagem': 'Chave Pix ja cadastrada'}), 400

        if chave_pix_telefone:
            cursor.execute("SELECT ID_CHAVE_PIX FROM CHAVE_PIX WHERE CHAVE_PIX_TELEFONE = ?", (chave_pix_telefone,))
            if cursor.fetchone():
                return jsonify({'mensagem': 'Chave Pix ja cadastrada'}), 400

        if chave_pix_cpf:
            cursor.execute("SELECT ID_CHAVE_PIX FROM CHAVE_PIX WHERE CHAVE_PIX_CPF = ?", (chave_pix_cpf,))
            if cursor.fetchone():
                return jsonify({'mensagem': 'Chave Pix ja cadastrada'}), 400

        if chave_pix_aleatoria:
            cursor.execute("SELECT ID_CHAVE_PIX FROM CHAVE_PIX WHERE CHAVE_PIX_ALEATORIA = ?", (chave_pix_aleatoria,))
            if cursor.fetchone():
                return jsonify({'mensagem': 'Chave Pix ja cadastrada'}), 400

        if chave_pix_cnpj:
            cursor.execute("SELECT ID_CHAVE_PIX FROM CHAVE_PIX WHERE CHAVE_PIX_CNPJ = ?", (chave_pix_cnpj,))
            if cursor.fetchone():
                return jsonify({'mensagem': 'Chave Pix ja cadastrada'}), 400

        if existe_chave_pix:
            id_chave_pix = existe_chave_pix[0]

            if not chave_pix_email:
                chave_pix_email = existe_chave_pix[1]

            if not chave_pix_telefone:
                chave_pix_telefone = existe_chave_pix[2]

            if not chave_pix_cpf:
                chave_pix_cpf = existe_chave_pix[3]

            if not chave_pix_aleatoria:
                chave_pix_aleatoria = existe_chave_pix[4]

            if not chave_pix_cnpj:
                chave_pix_cnpj = existe_chave_pix[5]

            cursor.execute("UPDATE CHAVE_PIX SET CHAVE_PIX_EMAIL = ?, CHAVE_PIX_TELEFONE = ?, CHAVE_PIX_CPF = ?, CHAVE_PIX_ALEATORIA = ?, CHAVE_PIX_CNPJ = ? WHERE ID_CHAVE_PIX = ? AND ID_CONTA = ?", (chave_pix_email, chave_pix_telefone, chave_pix_cpf, chave_pix_aleatoria, chave_pix_cnpj, id_chave_pix, id_conta))
            con.commit()

            return jsonify({
                'mensagem': 'Chave Pix cadastrada com sucesso',
                'id_chave_pix': id_chave_pix,
                'chave_pix_aleatoria': chave_pix_aleatoria
            }), 201

        cursor.execute("INSERT INTO CHAVE_PIX (ID_CONTA, CHAVE_PIX_EMAIL, CHAVE_PIX_TELEFONE, CHAVE_PIX_CPF, CHAVE_PIX_ALEATORIA, CHAVE_PIX_CNPJ) VALUES (?, ?, ?, ?, ?, ?) RETURNING ID_CHAVE_PIX", (id_conta, chave_pix_email, chave_pix_telefone, chave_pix_cpf, chave_pix_aleatoria, chave_pix_cnpj))
        id_chave_pix = cursor.fetchone()[0]

        con.commit()

        return jsonify({
            'mensagem': 'Chave Pix cadastrada com sucesso',
            'id_chave_pix': id_chave_pix,
            'chave_pix_aleatoria': chave_pix_aleatoria
        }), 201

    except Exception:
        con.rollback()
        return jsonify({'mensagem': 'Erro ao cadastrar chave Pix'}), 500

    finally:
        cursor.close()


@app.route('/edicao_chave_pix/<int:id_chave_pix>', methods=['PUT'])
def edicao_chave_pix(id_chave_pix):
    id_conta = descobre_id_conta()

    if id_conta is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = con.cursor()

    try:
        cursor.execute("SELECT ID_CHAVE_PIX, CHAVE_PIX_EMAIL, CHAVE_PIX_TELEFONE, CHAVE_PIX_CPF, CHAVE_PIX_ALEATORIA, CHAVE_PIX_CNPJ FROM CHAVE_PIX WHERE ID_CHAVE_PIX = ? AND ID_CONTA = ?", (id_chave_pix, id_conta))
        existe_chave_pix = cursor.fetchone()

        if not existe_chave_pix:
            return jsonify({'mensagem': 'Chave Pix nao encontrada'}), 404

        dados = request.get_json()

        chave_pix_email = dados.get('chave_pix_email', existe_chave_pix[1])
        chave_pix_telefone = dados.get('chave_pix_telefone', existe_chave_pix[2])
        chave_pix_cpf = dados.get('chave_pix_cpf', existe_chave_pix[3])
        chave_pix_aleatoria = dados.get('chave_pix_aleatoria', existe_chave_pix[4])
        chave_pix_cnpj = dados.get('chave_pix_cnpj', existe_chave_pix[5])

        chave_informada = chave_pix_email or chave_pix_telefone or chave_pix_cpf or chave_pix_aleatoria or chave_pix_cnpj

        if not chave_informada:
            return jsonify({'mensagem': 'Informe uma chave Pix'}), 400

        if chave_pix_email:
            cursor.execute("SELECT ID_CHAVE_PIX FROM CHAVE_PIX WHERE CHAVE_PIX_EMAIL = ? AND ID_CHAVE_PIX != ?", (chave_pix_email, id_chave_pix))
            if cursor.fetchone():
                return jsonify({'mensagem': 'Chave Pix ja cadastrada'}), 400

        if chave_pix_telefone:
            cursor.execute("SELECT ID_CHAVE_PIX FROM CHAVE_PIX WHERE CHAVE_PIX_TELEFONE = ? AND ID_CHAVE_PIX != ?", (chave_pix_telefone, id_chave_pix))
            if cursor.fetchone():
                return jsonify({'mensagem': 'Chave Pix ja cadastrada'}), 400

        if chave_pix_cpf:
            cursor.execute("SELECT ID_CHAVE_PIX FROM CHAVE_PIX WHERE CHAVE_PIX_CPF = ? AND ID_CHAVE_PIX != ?", (chave_pix_cpf, id_chave_pix))
            if cursor.fetchone():
                return jsonify({'mensagem': 'Chave Pix ja cadastrada'}), 400

        if chave_pix_aleatoria:
            cursor.execute("SELECT ID_CHAVE_PIX FROM CHAVE_PIX WHERE CHAVE_PIX_ALEATORIA = ? AND ID_CHAVE_PIX != ?", (chave_pix_aleatoria, id_chave_pix))
            if cursor.fetchone():
                return jsonify({'mensagem': 'Chave Pix ja cadastrada'}), 400

        if chave_pix_cnpj:
            cursor.execute("SELECT ID_CHAVE_PIX FROM CHAVE_PIX WHERE CHAVE_PIX_CNPJ = ? AND ID_CHAVE_PIX != ?", (chave_pix_cnpj, id_chave_pix))
            if cursor.fetchone():
                return jsonify({'mensagem': 'Chave Pix ja cadastrada'}), 400

        cursor.execute("UPDATE CHAVE_PIX SET CHAVE_PIX_EMAIL = ?, CHAVE_PIX_TELEFONE = ?, CHAVE_PIX_CPF = ?, CHAVE_PIX_ALEATORIA = ?, CHAVE_PIX_CNPJ = ? WHERE ID_CHAVE_PIX = ? AND ID_CONTA = ?", (chave_pix_email, chave_pix_telefone, chave_pix_cpf, chave_pix_aleatoria, chave_pix_cnpj, id_chave_pix, id_conta))
        con.commit()

        return jsonify({'mensagem': 'Chave Pix atualizada com sucesso'}), 200

    except Exception:
        con.rollback()
        return jsonify({'mensagem': 'Erro ao editar chave Pix'}), 500

    finally:
        cursor.close()


@app.route('/deletar_chave_pix/<int:id_chave_pix>', methods=['DELETE'])
def deletar_chave_pix(id_chave_pix):
    id_conta = descobre_id_conta()

    if id_conta is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    dados = request.get_json()
    tipo = dados.get('tipo')

    if not tipo:
        return jsonify({'mensagem': 'Informe o tipo da chave Pix'}), 400

    cursor = con.cursor()

    try:
        cursor.execute("SELECT ID_CHAVE_PIX, CHAVE_PIX_EMAIL, CHAVE_PIX_TELEFONE, CHAVE_PIX_CPF, CHAVE_PIX_ALEATORIA, CHAVE_PIX_CNPJ FROM CHAVE_PIX WHERE ID_CHAVE_PIX = ? AND ID_CONTA = ?", (id_chave_pix, id_conta))
        existe_chave_pix = cursor.fetchone()

        if not existe_chave_pix:
            return jsonify({'mensagem': 'Chave Pix nao encontrada'}), 404

        if tipo == 'email':
            if not existe_chave_pix[1]:
                return jsonify({'mensagem': 'Chave Pix nao encontrada'}), 404

            cursor.execute("UPDATE CHAVE_PIX SET CHAVE_PIX_EMAIL = ? WHERE ID_CHAVE_PIX = ? AND ID_CONTA = ?", (None, id_chave_pix, id_conta))

        elif tipo == 'telefone':
            if not existe_chave_pix[2]:
                return jsonify({'mensagem': 'Chave Pix nao encontrada'}), 404

            cursor.execute("UPDATE CHAVE_PIX SET CHAVE_PIX_TELEFONE = ? WHERE ID_CHAVE_PIX = ? AND ID_CONTA = ?", (None, id_chave_pix, id_conta))

        elif tipo == 'cpf':
            if not existe_chave_pix[3]:
                return jsonify({'mensagem': 'Chave Pix nao encontrada'}), 404

            cursor.execute("UPDATE CHAVE_PIX SET CHAVE_PIX_CPF = ? WHERE ID_CHAVE_PIX = ? AND ID_CONTA = ?", (None, id_chave_pix, id_conta))

        elif tipo == 'aleatoria':
            if not existe_chave_pix[4]:
                return jsonify({'mensagem': 'Chave Pix nao encontrada'}), 404

            cursor.execute("UPDATE CHAVE_PIX SET CHAVE_PIX_ALEATORIA = ? WHERE ID_CHAVE_PIX = ? AND ID_CONTA = ?", (None, id_chave_pix, id_conta))

        elif tipo == 'cnpj':
            if not existe_chave_pix[5]:
                return jsonify({'mensagem': 'Chave Pix nao encontrada'}), 404

            cursor.execute("UPDATE CHAVE_PIX SET CHAVE_PIX_CNPJ = ? WHERE ID_CHAVE_PIX = ? AND ID_CONTA = ?", (None, id_chave_pix, id_conta))

        else:
            return jsonify({'mensagem': 'Tipo de chave Pix invalido'}), 400

        con.commit()

        return jsonify({'mensagem': 'Chave Pix deletada com sucesso'}), 200

    except Exception:
        con.rollback()
        return jsonify({'mensagem': 'Erro ao deletar chave Pix'}), 500

    finally:
        cursor.close()


@app.route('/chaves_pix', methods=['GET'])
def chaves_pix():
    id_conta = descobre_id_conta()

    if id_conta is None:
        return jsonify({'mensagem': 'Usuário não logado'}), 403

    cursor = con.cursor()

    try:
        cursor.execute("SELECT ID_CHAVE_PIX, CHAVE_PIX_EMAIL, CHAVE_PIX_TELEFONE, CHAVE_PIX_CPF, CHAVE_PIX_ALEATORIA, CHAVE_PIX_CNPJ FROM CHAVE_PIX WHERE ID_CONTA = ?", (id_conta,))
        registros = cursor.fetchall()

        lista_chaves = []

        for registro in registros:
            id_chave_pix = registro[0]
            chave_pix_email = registro[1]
            chave_pix_telefone = registro[2]
            chave_pix_cpf = registro[3]
            chave_pix_aleatoria = registro[4]
            chave_pix_cnpj = registro[5]

            if chave_pix_email:
                lista_chaves.append({
                    'id_chave_pix': id_chave_pix,
                    'tipo': 'email',
                    'valor': chave_pix_email
                })

            if chave_pix_telefone:
                lista_chaves.append({
                    'id_chave_pix': id_chave_pix,
                    'tipo': 'telefone',
                    'valor': chave_pix_telefone
                })

            if chave_pix_cpf:
                lista_chaves.append({
                    'id_chave_pix': id_chave_pix,
                    'tipo': 'cpf',
                    'valor': chave_pix_cpf
                })

            if chave_pix_aleatoria:
                lista_chaves.append({
                    'id_chave_pix': id_chave_pix,
                    'tipo': 'aleatoria',
                    'valor': chave_pix_aleatoria
                })

            if chave_pix_cnpj:
                lista_chaves.append({
                    'id_chave_pix': id_chave_pix,
                    'tipo': 'cnpj',
                    'valor': chave_pix_cnpj
                })

        return jsonify({'chaves': lista_chaves}), 200

    except Exception:
        return jsonify({'mensagem': 'Erro ao buscar chaves Pix'}), 500

    finally:
        cursor.close()