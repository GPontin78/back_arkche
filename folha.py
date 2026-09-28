from flask import jsonify, request
from main import app
from banco import con
from funcao import descobre_id_conta, descobre_id_usuario, usuario_pode_acessar_conta


def contexto_folha_pj():
    id_usuario = descobre_id_usuario()
    id_conta = descobre_id_conta()

    if not id_usuario or not id_conta:
        return None, (jsonify({'mensagem': 'Usuario nao autenticado'}), 401)

    if not usuario_pode_acessar_conta(id_usuario, id_conta):
        return None, (jsonify({'mensagem': 'Usuario sem acesso a esta conta'}), 403)

    cursor = con.cursor()
    cursor.execute("SELECT TIPO_CONTA FROM CONTA WHERE ID_CONTA = ?", (id_conta,))
    conta = cursor.fetchone()
    cursor.close()

    if not conta:
        return None, (jsonify({'mensagem': 'Conta nao encontrada'}), 404)

    if conta[0] != 1:
        return None, (jsonify({'mensagem': 'Disponivel apenas para conta PJ'}), 403)

    return id_conta, None


@app.route('/adicionar_funcionario', methods=['POST'])
def adicionar_funcionario():
    id_conta, erro = contexto_folha_pj()

    if erro:
        return erro

    dados = request.get_json()
    cpf = dados.get('cpf')
    nome = dados.get('nome')
    salario = dados.get('salario')

    if not cpf or not nome or salario is None:
        return jsonify({'mensagem': 'Dados incompletos'}), 400

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("SELECT ID_FUNCIONARIO FROM FUNCIONARIO WHERE ID_CONTA_EMPRESA = ? AND CPF = ?", (id_conta, cpf))
        funcionario = cursor.fetchone()

        if funcionario:
            return jsonify({'mensagem': 'Funcionario ja cadastrado nesta empresa'}), 409

        cursor.execute("SELECT ID_USUARIO FROM USUARIO WHERE CPF = ?", (cpf,))
        usuario = cursor.fetchone()
        id_usuario = usuario[0] if usuario else None

        cursor.execute("INSERT INTO FUNCIONARIO (ID_CONTA_EMPRESA, ID_USUARIO, CPF, NOME, SALARIO, STATUS) VALUES (?, ?, ?, ?, ?, 1) RETURNING ID_FUNCIONARIO", (id_conta, id_usuario, cpf, nome, salario))
        id_funcionario = cursor.fetchone()[0]

        con.commit()

        return jsonify({
            'mensagem': 'Funcionario cadastrado com sucesso',
            'id_funcionario': id_funcionario,
            'id_usuario': id_usuario,
            'cpf': cpf,
            'nome': nome,
            'salario': float(salario),
            'status': 1,
            'possui_usuario_arkhe': id_usuario is not None
        }), 201

    except Exception as e:
        con.rollback()
        return jsonify({'mensagem': 'Erro ao cadastrar funcionario', 'erro': str(e)}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/listar_funcionarios', methods=['GET'])
def listar_funcionarios():
    id_conta, erro = contexto_folha_pj()

    if erro:
        return erro

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("SELECT F.ID_FUNCIONARIO, F.ID_USUARIO, F.CPF, F.NOME, F.SALARIO, F.STATUS, F.DATA_CADASTRO, C.ID_CONTA FROM FUNCIONARIO F LEFT JOIN CONTA C ON C.ID_USUARIO = F.ID_USUARIO AND C.TIPO_CONTA = 0 WHERE F.ID_CONTA_EMPRESA = ? ORDER BY F.STATUS DESC, F.NOME", (id_conta,))
        dados = cursor.fetchall()

        funcionarios = []

        for funcionario in dados:
            funcionarios.append({
                'id_funcionario': funcionario[0],
                'id_usuario': funcionario[1],
                'cpf': funcionario[2],
                'nome': funcionario[3],
                'salario': float(funcionario[4]),
                'status': funcionario[5],
                'data_cadastro': str(funcionario[6]),
                'id_conta_pf': funcionario[7],
                'possui_conta_arkhe': funcionario[7] is not None
            })

        return jsonify(funcionarios), 200

    except Exception as e:
        return jsonify({'mensagem': 'Erro ao listar funcionarios', 'erro': str(e)}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/editar_funcionario', methods=['PUT'])
def editar_funcionario():
    id_conta, erro = contexto_folha_pj()

    if erro:
        return erro

    dados = request.get_json()
    id_funcionario = dados.get('id_funcionario')
    nome = dados.get('nome')
    salario = dados.get('salario')

    if not id_funcionario or not nome or salario is None:
        return jsonify({'mensagem': 'Dados incompletos'}), 400

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("SELECT ID_FUNCIONARIO FROM FUNCIONARIO WHERE ID_FUNCIONARIO = ? AND ID_CONTA_EMPRESA = ?", (id_funcionario, id_conta))

        if not cursor.fetchone():
            return jsonify({'mensagem': 'Funcionario nao encontrado'}), 404

        cursor.execute("UPDATE FUNCIONARIO SET NOME = ?, SALARIO = ? WHERE ID_FUNCIONARIO = ? AND ID_CONTA_EMPRESA = ?", (nome, salario, id_funcionario, id_conta))

        con.commit()

        return jsonify({'mensagem': 'Funcionario atualizado com sucesso'}), 200

    except Exception as e:
        con.rollback()
        return jsonify({'mensagem': 'Erro ao editar funcionario', 'erro': str(e)}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/alterar_status_funcionario', methods=['PUT'])
def alterar_status_funcionario():
    id_conta, erro = contexto_folha_pj()

    if erro:
        return erro

    dados = request.get_json()
    id_funcionario = dados.get('id_funcionario')
    status = dados.get('status')

    if not id_funcionario or status is None:
        return jsonify({'mensagem': 'Dados incompletos'}), 400

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("SELECT ID_FUNCIONARIO FROM FUNCIONARIO WHERE ID_FUNCIONARIO = ? AND ID_CONTA_EMPRESA = ?", (id_funcionario, id_conta))

        if not cursor.fetchone():
            return jsonify({'mensagem': 'Funcionario nao encontrado'}), 404

        cursor.execute("UPDATE FUNCIONARIO SET STATUS = ? WHERE ID_FUNCIONARIO = ? AND ID_CONTA_EMPRESA = ?", (status, id_funcionario, id_conta))

        con.commit()

        return jsonify({'mensagem': 'Status alterado com sucesso'}), 200

    except Exception as e:
        con.rollback()
        return jsonify({'mensagem': 'Erro ao alterar status', 'erro': str(e)}), 500

    finally:
        if cursor:
            cursor.close()

@app.route('/criar_folha', methods=['POST'])
def criar_folha():
    id_conta, erro = contexto_folha_pj()

    if erro:
        return erro

    dados = request.get_json()
    mes = dados.get('mes')
    ano = dados.get('ano')

    if not mes or not ano:
        return jsonify({'mensagem': 'Mes e ano nao informados'}), 400

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("SELECT ID_FOLHA FROM FOLHA_PAGAMENTO WHERE ID_CONTA_EMPRESA = ? AND COMPETENCIA_MES = ? AND COMPETENCIA_ANO = ?", (id_conta, mes, ano))

        if cursor.fetchone():
            return jsonify({'mensagem': 'Ja existe uma folha para esta competencia'}), 409

        cursor.execute("SELECT ID_FUNCIONARIO, CPF, NOME, SALARIO FROM FUNCIONARIO WHERE ID_CONTA_EMPRESA = ? AND STATUS = 1 ORDER BY NOME", (id_conta,))
        funcionarios = cursor.fetchall()

        if not funcionarios:
            return jsonify({'mensagem': 'Nenhum funcionario ativo cadastrado'}), 400

        cursor.execute("INSERT INTO FOLHA_PAGAMENTO (ID_CONTA_EMPRESA, COMPETENCIA_MES, COMPETENCIA_ANO, STATUS) VALUES (?, ?, ?, 0) RETURNING ID_FOLHA", (id_conta, mes, ano))
        id_folha = cursor.fetchone()[0]

        for funcionario in funcionarios:
            id_funcionario = funcionario[0]
            cpf = funcionario[1]
            nome = funcionario[2]
            salario = funcionario[3]

            cursor.execute("""SELECT C.ID_CONTA FROM USUARIO U INNER JOIN CONTA C ON C.ID_USUARIO = U.ID_USUARIO WHERE U.CPF = ? AND C.TIPO_CONTA = 0 ORDER BY C.ID_CONTA ROWS 1""", (cpf,))
            conta_pf = cursor.fetchone()

            if conta_pf:
                id_conta_destino = conta_pf[0]
                status = 1
                erro_item = None
            else:
                id_conta_destino = None
                status = 0
                erro_item = 'Conta PF Arkhe nao encontrada'

            cursor.execute("INSERT INTO FOLHA_ITEM (ID_FOLHA, ID_FUNCIONARIO, ID_CONTA_DESTINO, CPF, NOME, VALOR, STATUS, ERRO) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (id_folha, id_funcionario, id_conta_destino, cpf, nome, salario, status, erro_item))

        con.commit()

        return jsonify({
            'mensagem': 'Folha criada com sucesso',
            'id_folha': id_folha
        }), 201

    except Exception as e:
        con.rollback()
        return jsonify({'mensagem': 'Erro ao criar folha', 'erro': str(e)}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/folha/<int:id_folha>', methods=['GET'])
def buscar_folha(id_folha):
    id_conta, erro = contexto_folha_pj()

    if erro:
        return erro

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("SELECT ID_FOLHA, COMPETENCIA_MES, COMPETENCIA_ANO, STATUS, DATA_CRIACAO, DATA_PAGAMENTO FROM FOLHA_PAGAMENTO WHERE ID_FOLHA = ? AND ID_CONTA_EMPRESA = ?", (id_folha, id_conta))
        folha = cursor.fetchone()

        if not folha:
            return jsonify({'mensagem': 'Folha nao encontrada'}), 404

        cursor.execute("SELECT ID_FOLHA_ITEM, ID_FUNCIONARIO, ID_CONTA_DESTINO, CPF, NOME, VALOR, STATUS, ERRO, ID_MOVIMENTACAO, DATA_PAGAMENTO FROM FOLHA_ITEM WHERE ID_FOLHA = ? ORDER BY NOME", (id_folha,))
        dados = cursor.fetchall()

        itens = []
        total = 0
        total_valido = 0
        total_pendente = 0
        quantidade_validos = 0
        quantidade_pendentes = 0

        for item in dados:
            valor = float(item[5])
            total += valor

            if item[6] == 1:
                total_valido += valor
                quantidade_validos += 1

            if item[6] == 0:
                total_pendente += valor
                quantidade_pendentes += 1

            itens.append({
                'id_item': item[0],
                'id_funcionario': item[1],
                'id_conta_destino': item[2],
                'cpf': item[3],
                'nome': item[4],
                'valor': valor,
                'status': item[6],
                'erro': item[7],
                'id_movimentacao': item[8],
                'data_pagamento': str(item[9]) if item[9] else None
            })

        return jsonify({
            'id_folha': folha[0],
            'mes': folha[1],
            'ano': folha[2],
            'status': folha[3],
            'data_criacao': str(folha[4]),
            'data_pagamento': str(folha[5]) if folha[5] else None,
            'total': total,
            'total_valido': total_valido,
            'total_pendente': total_pendente,
            'quantidade_funcionarios': len(itens),
            'quantidade_validos': quantidade_validos,
            'quantidade_pendentes': quantidade_pendentes,
            'itens': itens
        }), 200

    except Exception as e:
        return jsonify({'mensagem': 'Erro ao buscar folha', 'erro': str(e)}), 500

    finally:
        if cursor:
            cursor.close()