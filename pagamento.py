from flask import jsonify, request
from main import app, con
from funcao import descobre_id_usuario
from datetime import datetime

@app.route('/adicionar_receita', methods=['POST'])
def adicionar_receita():
    dados = request.get_json()
    descricao = dados.get('descricao').capitalize()
    valor =  float(dados.get('valor'))
    data_receita = dados.get('data_receita')
    tipo_conta = dados.get('tipo_conta')

    id_usuario = descobre_id_usuario()

    if id_usuario is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    if tipo_conta is None:
        return jsonify({'mensagem': 'Informe o tipo da conta'}), 400

    if tipo_conta != 0 and tipo_conta != 1:
            return jsonify({'mensagem': 'Tipo de conta invalido'}), 400

    try:
        cursor = con.cursor()
        if not descricao:
            return jsonify({'mensagem': 'Digite uma descrição', }), 400
        if not valor:
            return jsonify({'mensagem': 'Digite um valor', }), 400
        if not data_receita:
            return jsonify({'mensagem': 'Digite uma data', }), 400

        data_receita = datetime.strptime(data_receita, "%d/%m/%Y").date()

        cursor.execute("""
            select id_conta
            from conta
            where id_usuario = ?
            and tipo_conta = ?
        """, (id_usuario, tipo_conta))

        conta = cursor.fetchone()

        if not conta:
            return jsonify({'mensagem': 'Conta nao encontrada'}), 403

        id_conta = conta[0]

        cursor.execute("""insert into receita (descricao, valor, data_receita, id_usuario, id_conta) 
                          values(?,?,?,?,?)""", (descricao, valor, data_receita, id_usuario, id_conta))
        con.commit()

        return jsonify({'mensagem': 'Receita cadastrada com sucesso',}), 200

    except Exception:
        return jsonify({'mensagem': f'Erro ao cadastrar Receita'}), 500
    finally:
        cursor.close()

@app.route('/edicao_receita/<int:id_receita>', methods=['PUT'])
def edicao_receita(id_receita):
    id_usuario = descobre_id_usuario()

    if id_usuario is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = con.cursor()

    try:
        cursor.execute("""
            select id_receita, descricao, valor, data_receita
            from receita
            where id_receita = ?
            and id_usuario = ?
        """, (id_receita, id_usuario))

        existe_receita = cursor.fetchone()

        if not existe_receita:
            return jsonify({'mensagem': 'Receita não encontrada'}), 404

        dados = request.get_json()

        descricao = dados.get('descricao', existe_receita[1]).capitalize()
        valor = float(dados.get('valor', existe_receita[2]))
        data_receita = dados.get('data_receita')

        if data_receita:
            data_receita = datetime.strptime(data_receita, "%d/%m/%Y").date()
        else:
            data_receita = existe_receita[3]


        cursor.execute("""
            update receita
            set descricao = ?, valor = ?, data_receita = ?
            where id_receita = ?
            and id_usuario = ?
        """, (descricao, valor, data_receita, id_receita, id_usuario))

        con.commit()

        return jsonify({'mensagem': 'Receita atualizada com sucesso'}), 200

    except Exception as e:
        return jsonify({
            'mensagem': f'Erro ao editar receita: {str(e)}'
        }), 500

    finally:
        cursor.close()

@app.route('/deletar_receita/<int:id_receita>', methods=['DELETE'])
def deletar_receita(id_receita):
    id_usuario = descobre_id_usuario()

    if id_usuario is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = con.cursor()
    cursor.execute("""select id_receita, descricao, valor, data_receita       
                        from receita where id_receita=? and id_usuario=?""", (id_receita, id_usuario))
    existe_receita = cursor.fetchone()
    if not existe_receita:
        return jsonify({'mensagem': 'Não existe despesa'})
    try:
        cursor = con.cursor()
        cursor.execute("""delete from receita where id_receita=? and id_usuario=?""",
                       (id_receita, id_usuario))
        con.commit()
        return jsonify({'mensagem': 'Receita deletada com sucesso'})
    except Exception as e:
        return jsonify({'mensagem': 'Erro ao deletar Receita'})
    finally:
        cursor.close()



@app.route('/adicionar_despesa', methods=['POST'])
def adicionar_despesa():
    dados = request.get_json()
    descricao = dados.get('descricao').capitalize()
    valor =  float(dados.get('valor'))
    data_despesa = dados.get('data_despesa')
    tipo_conta = dados.get('tipo_conta')

    id_usuario = descobre_id_usuario()

    if id_usuario is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    if tipo_conta is None:
        return jsonify({'mensagem': 'Informe o tipo da conta'}), 400

    if tipo_conta != 0 and tipo_conta != 1:
            return jsonify({'mensagem': 'Tipo de conta invalido'}), 400

    try:
        cursor = con.cursor()
        if not descricao:
            return jsonify({'mensagem': 'Digite uma descrição', }), 400
        if not valor:
            return jsonify({'mensagem': 'Digite um valor', }), 400
        if not data_despesa:
            return jsonify({'mensagem': 'Digite uma data', }), 400

        data_despesa = datetime.strptime(data_despesa, "%d/%m/%Y").date()

        cursor.execute("""
            select id_conta
            from conta
            where id_usuario = ?
            and tipo_conta = ?
        """, (id_usuario, tipo_conta))

        conta = cursor.fetchone()

        if not conta:
            return jsonify({'mensagem': 'Conta nao encontrada'}), 403

        id_conta = conta[0]

        cursor.execute("""insert into despesa (descricao, valor, data_despesa, id_usuario, id_conta) 
                          values(?,?,?,?,?)""", (descricao, valor, data_despesa, id_usuario, id_conta))
        con.commit()

        return jsonify({'mensagem': 'Despesa cadastrada com sucesso',}), 200

    except Exception:
        return jsonify({'mensagem': f'Erro ao cadastrar Despesa'}), 500
    finally:
        cursor.close()


@app.route('/edicao_despesa/<int:id_despesa>', methods=['PUT'])
def edicao_despesa(id_despesa):
    id_usuario = descobre_id_usuario()

    if id_usuario is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = con.cursor()

    try:
        cursor.execute("""
            select id_despesa, descricao, valor, data_despesa
            from despesa
            where id_despesa = ?
            and id_usuario = ?
        """, (id_despesa, id_usuario))

        existe_despesa = cursor.fetchone()

        if not existe_despesa:
            return jsonify({'mensagem': 'Despesa não encontrada'}), 404

        dados = request.get_json()

        descricao = dados.get('descricao', existe_despesa[1]).capitalize()
        valor = float(dados.get('valor', existe_despesa[2]))
        data_despesa = dados.get('data_despesa')

        if data_despesa:
            data_despesa = datetime.strptime(data_despesa, "%d/%m/%Y").date()
        else:
            data_despesa = existe_despesa[3]


        cursor.execute("""
            update despesa
            set descricao = ?, valor = ?, data_despesa = ?
            where id_despesa = ?
            and id_usuario = ?
        """, (descricao, valor, data_despesa, id_despesa, id_usuario))

        con.commit()

        return jsonify({'mensagem': 'Despesa atualizada com sucesso'}), 200

    except Exception as e:
        return jsonify({
            'mensagem': f'Erro ao editar despesa: {str(e)}'
        }), 500

    finally:
        cursor.close()

@app.route('/deletar_depesa/<int:id_despesa>', methods=['DELETE'])
def deletar_depesa(id_despesa):
    id_usuario = descobre_id_usuario()

    if id_usuario is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = con.cursor()
    cursor.execute("""select id_despesa, descricao, valor, data_despesa       
                        from despesa where id_despesa=? and id_usuario=?""", (id_despesa, id_usuario))
    existe_despesa = cursor.fetchone()
    if not existe_despesa:
        return jsonify({'mensagem': 'Não existe despesa'})
    try:
        cursor = con.cursor()
        cursor.execute("""delete from despesa where id_despesa=? and id_usuario=?""",
                       (id_despesa, id_usuario))
        con.commit()
        return jsonify({'mensagem': 'Despesa deletada com sucesso'})
    except Exception as e:
        return jsonify({'mensagem': 'Erro ao deletar Despesa'})
    finally:
        cursor.close()
