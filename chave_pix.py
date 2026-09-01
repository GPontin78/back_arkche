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
            select id_chave_pix,
                   chave_pix_email,
                   chave_pix_telefone,
                   chave_pix_cpf,
                   chave_pix_aleatoria,
                   chave_pix_cnpj
            from chave_pix
            where id_usuario = ?
        """, (id_usuario,))

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
            cursor.execute("""
                select id_usuario
                from chave_pix
                where chave_pix_email = ?
            """, (chave_pix_email,))

            chave_existente = cursor.fetchone()

            if chave_existente:
                if chave_existente[0] != id_usuario:
                    return jsonify({'mensagem': 'Chave Pix ja cadastrada'}), 400

        if chave_pix_telefone:
            cursor.execute("""
                select id_usuario
                from chave_pix
                where chave_pix_telefone = ?
            """, (chave_pix_telefone,))

            chave_existente = cursor.fetchone()

            if chave_existente:
                if chave_existente[0] != id_usuario:
                    return jsonify({'mensagem': 'Chave Pix ja cadastrada'}), 400

        if chave_pix_cpf:
            cursor.execute("""
                select id_usuario
                from chave_pix
                where chave_pix_cpf = ?
            """, (chave_pix_cpf,))

            chave_existente = cursor.fetchone()

            if chave_existente:
                if chave_existente[0] != id_usuario:
                    return jsonify({'mensagem': 'Chave Pix ja cadastrada'}), 400

        if chave_pix_aleatoria:
            cursor.execute("""
                select id_usuario
                from chave_pix
                where chave_pix_aleatoria = ?
            """, (chave_pix_aleatoria,))

            chave_existente = cursor.fetchone()

            if chave_existente:
                if chave_existente[0] != id_usuario:
                    return jsonify({'mensagem': 'Chave Pix ja cadastrada'}), 400

        if chave_pix_cnpj:
            cursor.execute("""
                select id_usuario
                from chave_pix
                where chave_pix_cnpj = ?
            """, (chave_pix_cnpj,))

            chave_existente = cursor.fetchone()

            if chave_existente:
                if chave_existente[0] != id_usuario:
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

            return jsonify({
                'mensagem': 'Chave Pix cadastrada com sucesso',
                'id_chave_pix': id_chave_pix,
                'chave_pix_aleatoria': chave_pix_aleatoria
            }), 201

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
            select id_chave_pix,
                   chave_pix_email,
                   chave_pix_telefone,
                   chave_pix_cpf,
                   chave_pix_aleatoria,
                   chave_pix_cnpj
            from chave_pix
            where id_chave_pix = ?
            and id_usuario = ?
        """, (id_chave_pix, id_usuario))

        existe_chave_pix = cursor.fetchone()

        if not existe_chave_pix:
            return jsonify({'mensagem': 'Chave Pix nao encontrada'}), 404

        dados = request.get_json()

        chave_pix_email = dados.get(
            'chave_pix_email',
            existe_chave_pix[1]
        )

        chave_pix_telefone = dados.get(
            'chave_pix_telefone',
            existe_chave_pix[2]
        )

        chave_pix_cpf = dados.get(
            'chave_pix_cpf',
            existe_chave_pix[3]
        )

        chave_pix_aleatoria = dados.get(
            'chave_pix_aleatoria',
            existe_chave_pix[4]
        )

        chave_pix_cnpj = dados.get(
            'chave_pix_cnpj',
            existe_chave_pix[5]
        )

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

        return jsonify({
            'mensagem': 'Chave Pix atualizada com sucesso'
        }), 200

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

    dados = request.get_json()
    tipo = dados.get('tipo')

    if not tipo:
        return jsonify({'mensagem': 'Informe o tipo da chave Pix'}), 400

    cursor = con.cursor()

    try:
        cursor.execute("""
            select id_chave_pix,
                   chave_pix_email,
                   chave_pix_telefone,
                   chave_pix_cpf,
                   chave_pix_aleatoria,
                   chave_pix_cnpj
            from chave_pix
            where id_chave_pix = ?
            and id_usuario = ?
        """, (id_chave_pix, id_usuario))

        existe_chave_pix = cursor.fetchone()

        if not existe_chave_pix:
            return jsonify({'mensagem': 'Chave Pix nao encontrada'}), 404

        if tipo == 'email':
            if not existe_chave_pix[1]:
                return jsonify({'mensagem': 'Chave Pix nao encontrada'}), 404

            cursor.execute("""
                update chave_pix
                set chave_pix_email = ?
                where id_chave_pix = ?
                and id_usuario = ?
            """, (None, id_chave_pix, id_usuario))

        elif tipo == 'telefone':
            if not existe_chave_pix[2]:
                return jsonify({'mensagem': 'Chave Pix nao encontrada'}), 404

            cursor.execute("""
                update chave_pix
                set chave_pix_telefone = ?
                where id_chave_pix = ?
                and id_usuario = ?
            """, (None, id_chave_pix, id_usuario))

        elif tipo == 'cpf':
            if not existe_chave_pix[3]:
                return jsonify({'mensagem': 'Chave Pix nao encontrada'}), 404

            cursor.execute("""
                update chave_pix
                set chave_pix_cpf = ?
                where id_chave_pix = ?
                and id_usuario = ?
            """, (None, id_chave_pix, id_usuario))

        elif tipo == 'aleatoria':
            if not existe_chave_pix[4]:
                return jsonify({'mensagem': 'Chave Pix nao encontrada'}), 404

            cursor.execute("""
                update chave_pix
                set chave_pix_aleatoria = ?
                where id_chave_pix = ?
                and id_usuario = ?
            """, (None, id_chave_pix, id_usuario))

        elif tipo == 'cnpj':
            if not existe_chave_pix[5]:
                return jsonify({'mensagem': 'Chave Pix nao encontrada'}), 404

            cursor.execute("""
                update chave_pix
                set chave_pix_cnpj = ?
                where id_chave_pix = ?
                and id_usuario = ?
            """, (None, id_chave_pix, id_usuario))

        else:
            return jsonify({'mensagem': 'Tipo de chave Pix invalido'}), 400

        con.commit()

        return jsonify({
            'mensagem': 'Chave Pix deletada com sucesso'
        }), 200

    except Exception:
        con.rollback()
        return jsonify({'mensagem': 'Erro ao deletar chave Pix'}), 500

    finally:
        cursor.close()


@app.route('/chaves_pix', methods=['GET'])
def chaves_pix():
    id_usuario = descobre_id_usuario()

    if id_usuario is None:
        return jsonify({'mensagem': 'Usuário não logado'}), 403

    cursor = con.cursor()

    try:
        cursor.execute("""
            SELECT
                id_chave_pix,
                chave_pix_email,
                chave_pix_telefone,
                chave_pix_cpf,
                chave_pix_aleatoria,
                chave_pix_cnpj
            FROM chave_pix
            WHERE id_usuario = ?
        """, (id_usuario,))

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

        return jsonify({
            'chaves': lista_chaves
        }), 200

    except Exception:
        return jsonify({
            'mensagem': 'Erro ao buscar chaves Pix'
        }), 500

    finally:
        cursor.close()