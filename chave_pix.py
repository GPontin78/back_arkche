from flask import jsonify, request
from main import app, con
from funcao import descobre_id_usuario
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

    id_usuario = descobre_id_usuario()

    if id_usuario is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    chave_informada = chave_pix_email or chave_pix_telefone or chave_pix_cpf or chave_pix_aleatoria or chave_pix_cnpj

    if not chave_informada:
        return jsonify({'mensagem': 'Informe uma chave Pix'}), 400

    cursor = con.cursor()

    try:
        cursor.execute("""
            select id_conta
            from conta
            where id_usuario = ?
        """, (id_usuario,))

        conta = cursor.fetchone()

        if not conta:
            return jsonify({'mensagem': 'Conta nao encontrada'}), 403

        cursor.execute("""
            select 1
            from chave_pix
            where id_usuario = ?
        """, (id_usuario,))

        if cursor.fetchone():
            return jsonify({'mensagem': 'Chaves Pix ja cadastradas'}), 400

        if chave_pix_email:
            cursor.execute("""
                select 1
                from chave_pix
                where chave_pix_email = ?
            """, (chave_pix_email,))

            if cursor.fetchone():
                return jsonify({'mensagem': 'Chave Pix ja cadastrada'}), 400

        if chave_pix_telefone:
            cursor.execute("""
                select 1
                from chave_pix
                where chave_pix_telefone = ?
            """, (chave_pix_telefone,))

            if cursor.fetchone():
                return jsonify({'mensagem': 'Chave Pix ja cadastrada'}), 400

        if chave_pix_cpf:
            cursor.execute("""
                select 1
                from chave_pix
                where chave_pix_cpf = ?
            """, (chave_pix_cpf,))

            if cursor.fetchone():
                return jsonify({'mensagem': 'Chave Pix ja cadastrada'}), 400

        if chave_pix_aleatoria:
            cursor.execute("""
                select 1
                from chave_pix
                where chave_pix_aleatoria = ?
            """, (chave_pix_aleatoria,))

            if cursor.fetchone():
                return jsonify({'mensagem': 'Chave Pix ja cadastrada'}), 400

        if chave_pix_cnpj:
            cursor.execute("""
                select 1
                from chave_pix
                where chave_pix_cnpj = ?
            """, (chave_pix_cnpj,))

            if cursor.fetchone():
                return jsonify({'mensagem': 'Chave Pix ja cadastrada'}), 400

        cursor.execute("""
            insert into chave_pix (
                id_usuario,
                chave_pix_email,
                chave_pix_telefone,
                chave_pix_cpf,
                chave_pix_aleatoria,
                chave_pix_cnpj
            ) values (?, ?, ?, ?, ?, ?)
            returning id_chave_pix
        """, (
            id_usuario,
            chave_pix_email,
            chave_pix_telefone,
            chave_pix_cpf,
            chave_pix_aleatoria,
            chave_pix_cnpj
        ))

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
    id_usuario = descobre_id_usuario()

    if id_usuario is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = con.cursor()

    try:
        cursor.execute("""
            select id_chave_pix, chave_pix_email, chave_pix_telefone,
                   chave_pix_cpf, chave_pix_aleatoria, chave_pix_cnpj
            from chave_pix
            where id_chave_pix = ?
            and id_usuario = ?
        """, (id_chave_pix, id_usuario))

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
            cursor.execute("""
                select 1
                from chave_pix
                where chave_pix_email = ?
                and id_chave_pix != ?
            """, (chave_pix_email, id_chave_pix))

            if cursor.fetchone():
                return jsonify({'mensagem': 'Chave Pix ja cadastrada'}), 400

        if chave_pix_telefone:
            cursor.execute("""
                select 1
                from chave_pix
                where chave_pix_telefone = ?
                and id_chave_pix != ?
            """, (chave_pix_telefone, id_chave_pix))

            if cursor.fetchone():
                return jsonify({'mensagem': 'Chave Pix ja cadastrada'}), 400

        if chave_pix_cpf:
            cursor.execute("""
                select 1
                from chave_pix
                where chave_pix_cpf = ?
                and id_chave_pix != ?
            """, (chave_pix_cpf, id_chave_pix))

            if cursor.fetchone():
                return jsonify({'mensagem': 'Chave Pix ja cadastrada'}), 400

        if chave_pix_aleatoria:
            cursor.execute("""
                select 1
                from chave_pix
                where chave_pix_aleatoria = ?
                and id_chave_pix != ?
            """, (chave_pix_aleatoria, id_chave_pix))

            if cursor.fetchone():
                return jsonify({'mensagem': 'Chave Pix ja cadastrada'}), 400

        if chave_pix_cnpj:
            cursor.execute("""
                select 1
                from chave_pix
                where chave_pix_cnpj = ?
                and id_chave_pix != ?
            """, (chave_pix_cnpj, id_chave_pix))

            if cursor.fetchone():
                return jsonify({'mensagem': 'Chave Pix ja cadastrada'}), 400

        cursor.execute("""
            update chave_pix
            set chave_pix_email = ?,
                chave_pix_telefone = ?,
                chave_pix_cpf = ?,
                chave_pix_aleatoria = ?,
                chave_pix_cnpj = ?
            where id_chave_pix = ?
            and id_usuario = ?
        """, (
            chave_pix_email,
            chave_pix_telefone,
            chave_pix_cpf,
            chave_pix_aleatoria,
            chave_pix_cnpj,
            id_chave_pix,
            id_usuario
        ))

        con.commit()

        return jsonify({'mensagem': 'Chave Pix atualizada com sucesso'}), 200

    except Exception:
        con.rollback()
        return jsonify({'mensagem': 'Erro ao editar chave Pix'}), 500

    finally:
        cursor.close()


@app.route('/deletar_chave_pix/<int:id_chave_pix>', methods=['DELETE'])
def deletar_chave_pix(id_chave_pix):
    id_usuario = descobre_id_usuario()

    if id_usuario is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = con.cursor()

    try:
        cursor.execute("""
            select id_chave_pix
            from chave_pix
            where id_chave_pix = ?
            and id_usuario = ?
        """, (id_chave_pix, id_usuario))

        existe_chave_pix = cursor.fetchone()

        if not existe_chave_pix:
            return jsonify({'mensagem': 'Chave Pix nao encontrada'}), 404

        cursor.execute("""
            delete from chave_pix
            where id_chave_pix = ?
            and id_usuario = ?
        """, (id_chave_pix, id_usuario))

        con.commit()

        return jsonify({'mensagem': 'Chave Pix deletada com sucesso'}), 200

    except Exception:
        con.rollback()
        return jsonify({'mensagem': 'Erro ao deletar chave Pix'}), 500

    finally:
        cursor.close()
