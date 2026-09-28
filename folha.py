from flask import jsonify, request
from main import app
from banco import con
from funcao import descobre_id_conta, descobre_id_usuario, usuario_pode_acessar_conta, calcular_saldo, data_atual


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
        folha_existente = cursor.fetchone()

        if folha_existente:
            return jsonify({'mensagem': 'Ja existe uma folha para esta competencia', 'id_folha': folha_existente[0]}), 409

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


@app.route('/editar_folha', methods=['PUT'])
def editar_folha():
    id_conta, erro = contexto_folha_pj()

    if erro:
        return erro

    dados = request.get_json() or {}
    id_folha = dados.get('id_folha')
    mes = dados.get('mes')
    ano = dados.get('ano')

    if not id_folha or not mes or not ano:
        return jsonify({'mensagem': 'Folha, mes e ano sao obrigatorios'}), 400

    try:
        mes = int(mes)
        ano = int(ano)
    except Exception:
        return jsonify({'mensagem': 'Mes ou ano invalido'}), 400

    if mes < 1 or mes > 12 or ano < 2000 or ano > 2200:
        return jsonify({'mensagem': 'Competencia invalida'}), 400

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("SELECT STATUS FROM FOLHA_PAGAMENTO WHERE ID_FOLHA = ? AND ID_CONTA_EMPRESA = ?", (id_folha, id_conta))
        folha = cursor.fetchone()

        if not folha:
            return jsonify({'mensagem': 'Folha nao encontrada'}), 404

        if folha[0] != 0:
            return jsonify({'mensagem': 'Somente folhas em rascunho podem ser editadas'}), 409

        cursor.execute("SELECT COUNT(*) FROM FOLHA_ITEM WHERE ID_FOLHA = ? AND ID_MOVIMENTACAO IS NOT NULL", (id_folha,))
        if cursor.fetchone()[0] > 0:
            return jsonify({'mensagem': 'Esta folha possui movimentacoes e nao pode ser editada'}), 409

        cursor.execute("SELECT ID_FOLHA FROM FOLHA_PAGAMENTO WHERE ID_CONTA_EMPRESA = ? AND COMPETENCIA_MES = ? AND COMPETENCIA_ANO = ? AND ID_FOLHA <> ?", (id_conta, mes, ano, id_folha))
        existente = cursor.fetchone()

        if existente:
            return jsonify({'mensagem': 'Ja existe uma folha para esta competencia', 'id_folha': existente[0]}), 409

        cursor.execute("SELECT ID_FUNCIONARIO, CPF, NOME, SALARIO FROM FUNCIONARIO WHERE ID_CONTA_EMPRESA = ? AND STATUS = 1 ORDER BY NOME", (id_conta,))
        funcionarios = cursor.fetchall()

        if not funcionarios:
            return jsonify({'mensagem': 'Nenhum funcionario ativo cadastrado'}), 400

        cursor.execute("DELETE FROM FOLHA_ITEM WHERE ID_FOLHA = ?", (id_folha,))
        cursor.execute("UPDATE FOLHA_PAGAMENTO SET COMPETENCIA_MES = ?, COMPETENCIA_ANO = ?, STATUS = 0, DATA_PAGAMENTO = NULL WHERE ID_FOLHA = ? AND ID_CONTA_EMPRESA = ?", (mes, ano, id_folha, id_conta))

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

        return jsonify({'mensagem': 'Rascunho atualizado com sucesso', 'id_folha': id_folha}), 200

    except Exception as e:
        con.rollback()
        return jsonify({'mensagem': 'Erro ao editar folha', 'erro': str(e)}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/folha/<int:id_folha>', methods=['DELETE'])
def excluir_folha(id_folha):
    id_conta, erro = contexto_folha_pj()

    if erro:
        return erro

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("SELECT STATUS FROM FOLHA_PAGAMENTO WHERE ID_FOLHA = ? AND ID_CONTA_EMPRESA = ?", (id_folha, id_conta))
        folha = cursor.fetchone()

        if not folha:
            return jsonify({'mensagem': 'Folha nao encontrada'}), 404

        if folha[0] != 0:
            return jsonify({'mensagem': 'Somente folhas em rascunho podem ser excluidas'}), 409

        cursor.execute("SELECT COUNT(*) FROM FOLHA_ITEM WHERE ID_FOLHA = ? AND ID_MOVIMENTACAO IS NOT NULL", (id_folha,))
        if cursor.fetchone()[0] > 0:
            return jsonify({'mensagem': 'Esta folha possui movimentacoes e nao pode ser excluida'}), 409

        cursor.execute("DELETE FROM FOLHA_ITEM WHERE ID_FOLHA = ?", (id_folha,))
        cursor.execute("DELETE FROM FOLHA_PAGAMENTO WHERE ID_FOLHA = ? AND ID_CONTA_EMPRESA = ?", (id_folha, id_conta))

        con.commit()

        return jsonify({'mensagem': 'Rascunho excluido com sucesso', 'id_folha': id_folha}), 200

    except Exception as e:
        con.rollback()
        return jsonify({'mensagem': 'Erro ao excluir folha', 'erro': str(e)}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/listar_folhas', methods=['GET'])
def listar_folhas():
    id_conta, erro = contexto_folha_pj()

    if erro:
        return erro

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("""SELECT FP.ID_FOLHA, FP.COMPETENCIA_MES, FP.COMPETENCIA_ANO, FP.STATUS, FP.DATA_CRIACAO, FP.DATA_PAGAMENTO,
                                 CAST(COALESCE(SUM(FI.VALOR), 0) AS DECIMAL(18,2)),
                                 CAST(COALESCE(SUM(CASE WHEN FI.STATUS = 2 THEN FI.VALOR ELSE 0 END), 0) AS DECIMAL(18,2)),
                                 CAST(COALESCE(SUM(CASE WHEN FI.STATUS = 1 THEN FI.VALOR ELSE 0 END), 0) AS DECIMAL(18,2)),
                                 CAST(COALESCE(SUM(CASE WHEN FI.STATUS = 0 THEN FI.VALOR ELSE 0 END), 0) AS DECIMAL(18,2)),
                                 COUNT(FI.ID_FOLHA_ITEM),
                                 SUM(CASE WHEN FI.STATUS = 2 THEN 1 ELSE 0 END),
                                 SUM(CASE WHEN FI.STATUS = 1 THEN 1 ELSE 0 END),
                                 SUM(CASE WHEN FI.STATUS = 0 THEN 1 ELSE 0 END)
                          FROM FOLHA_PAGAMENTO FP
                          LEFT JOIN FOLHA_ITEM FI ON FI.ID_FOLHA = FP.ID_FOLHA
                          WHERE FP.ID_CONTA_EMPRESA = ?
                          GROUP BY FP.ID_FOLHA, FP.COMPETENCIA_MES, FP.COMPETENCIA_ANO, FP.STATUS, FP.DATA_CRIACAO, FP.DATA_PAGAMENTO
                          ORDER BY FP.COMPETENCIA_ANO DESC, FP.COMPETENCIA_MES DESC, FP.ID_FOLHA DESC""", (id_conta,))

        dados = cursor.fetchall()
        folhas = []

        for folha in dados:
            folhas.append({
                'id_folha': folha[0],
                'mes': folha[1],
                'ano': folha[2],
                'status': folha[3],
                'data_criacao': str(folha[4]) if folha[4] else None,
                'data_pagamento': str(folha[5]) if folha[5] else None,
                'total': float(folha[6]),
                'total_pago': float(folha[7]),
                'total_valido': float(folha[8]),
                'total_pendente': float(folha[9]),
                'quantidade_funcionarios': folha[10],
                'quantidade_pagos': folha[11] or 0,
                'quantidade_validos': folha[12] or 0,
                'quantidade_pendentes': folha[13] or 0
            })

        return jsonify({'folhas': folhas, 'total': len(folhas)}), 200

    except Exception as e:
        return jsonify({'mensagem': 'Erro ao listar folhas', 'erro': str(e)}), 500

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
        total_pago = 0
        quantidade_validos = 0
        quantidade_pendentes = 0
        quantidade_pagos = 0

        for item in dados:
            valor = float(item[5])
            total += valor

            if item[6] == 1:
                total_valido += valor
                quantidade_validos += 1

            if item[6] == 0:
                total_pendente += valor
                quantidade_pendentes += 1

            if item[6] == 2:
                total_pago += valor
                quantidade_pagos += 1

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
            'total_pago': total_pago,
            'quantidade_funcionarios': len(itens),
            'quantidade_validos': quantidade_validos,
            'quantidade_pendentes': quantidade_pendentes,
            'quantidade_pagos': quantidade_pagos,
            'itens': itens
        }), 200

    except Exception as e:
        return jsonify({'mensagem': 'Erro ao buscar folha', 'erro': str(e)}), 500

    finally:
        if cursor:
            cursor.close()
@app.route('/revalidar_folha', methods=['POST'])
def revalidar_folha():
    id_conta, erro = contexto_folha_pj()

    if erro:
        return erro

    dados = request.get_json()
    id_folha = dados.get('id_folha')

    if not id_folha:
        return jsonify({'mensagem': 'Folha nao informada'}), 400

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("SELECT STATUS FROM FOLHA_PAGAMENTO WHERE ID_FOLHA = ? AND ID_CONTA_EMPRESA = ?", (id_folha, id_conta))
        folha = cursor.fetchone()

        if not folha:
            return jsonify({'mensagem': 'Folha nao encontrada'}), 404

        if folha[0] == 2:
            return jsonify({'mensagem': 'Folha esta sendo processada'}), 409

        cursor.execute("SELECT ID_FOLHA_ITEM, ID_FUNCIONARIO, CPF FROM FOLHA_ITEM WHERE ID_FOLHA = ? AND STATUS = 0 AND ID_MOVIMENTACAO IS NULL", (id_folha,))
        itens = cursor.fetchall()

        revalidados = 0

        for item in itens:
            id_item = item[0]
            id_funcionario = item[1]
            cpf = item[2]

            cursor.execute("""SELECT U.ID_USUARIO, C.ID_CONTA FROM USUARIO U INNER JOIN CONTA C ON C.ID_USUARIO = U.ID_USUARIO WHERE U.CPF = ? AND C.TIPO_CONTA = 0 ORDER BY C.ID_CONTA ROWS 1""", (cpf,))
            conta = cursor.fetchone()

            if conta:
                id_usuario = conta[0]
                id_conta_destino = conta[1]

                cursor.execute("UPDATE FOLHA_ITEM SET ID_CONTA_DESTINO = ?, STATUS = 1, ERRO = NULL WHERE ID_FOLHA_ITEM = ?", (id_conta_destino, id_item))
                cursor.execute("UPDATE FUNCIONARIO SET ID_USUARIO = ? WHERE ID_FUNCIONARIO = ? AND ID_CONTA_EMPRESA = ?", (id_usuario, id_funcionario, id_conta))

                revalidados += 1

        cursor.execute("SELECT COUNT(*) FROM FOLHA_ITEM WHERE ID_FOLHA = ? AND STATUS = 0", (id_folha,))
        pendentes = cursor.fetchone()[0]

        if pendentes == 0 and folha[0] in (0, 1):
            cursor.execute("UPDATE FOLHA_PAGAMENTO SET STATUS = 1 WHERE ID_FOLHA = ?", (id_folha,))

        con.commit()

        return jsonify({
            'mensagem': 'Folha revalidada com sucesso',
            'id_folha': id_folha,
            'revalidados': revalidados,
            'pendentes': pendentes
        }), 200

    except Exception as e:
        con.rollback()
        return jsonify({'mensagem': 'Erro ao revalidar folha', 'erro': str(e)}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/pagar_folha', methods=['POST'])
def pagar_folha():
    id_conta, erro = contexto_folha_pj()

    if erro:
        return erro

    dados = request.get_json()
    id_folha = dados.get('id_folha')

    if not id_folha:
        return jsonify({'mensagem': 'Folha nao informada'}), 400

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("SELECT STATUS FROM FOLHA_PAGAMENTO WHERE ID_FOLHA = ? AND ID_CONTA_EMPRESA = ?", (id_folha, id_conta))
        folha = cursor.fetchone()

        if not folha:
            return jsonify({'mensagem': 'Folha nao encontrada'}), 404

        if folha[0] == 3:
            return jsonify({'mensagem': 'Esta folha ja foi paga'}), 400

        if folha[0] == 2:
            return jsonify({'mensagem': 'Esta folha esta sendo processada'}), 409

        cursor.execute("UPDATE FOLHA_PAGAMENTO SET STATUS = 2 WHERE ID_FOLHA = ? AND ID_CONTA_EMPRESA = ? AND STATUS IN (0,1,4) RETURNING ID_FOLHA", (id_folha, id_conta))
        bloqueio = cursor.fetchone()

        if not bloqueio:
            con.rollback()
            return jsonify({'mensagem': 'Folha ja paga ou em processamento'}), 409

        cursor.execute("SELECT ID_FOLHA_ITEM, ID_CONTA_DESTINO, VALOR FROM FOLHA_ITEM WHERE ID_FOLHA = ? AND STATUS = 1 AND ID_MOVIMENTACAO IS NULL", (id_folha,))
        itens = cursor.fetchall()

        if not itens:
            con.rollback()
            return jsonify({'mensagem': 'Nenhum pagamento disponivel nesta folha'}), 400

        total = sum(float(item[2]) for item in itens)
        saldo = calcular_saldo(id_conta)

        if saldo < total:
            con.rollback()

            return jsonify({
                'mensagem': 'Saldo insuficiente para pagar a folha',
                'saldo': float(saldo),
                'total_folha': total
            }), 400

        pagamentos = []

        for item in itens:
            id_item = item[0]
            id_destino = item[1]
            valor = item[2]
            data_movimentacao = data_atual()

            cursor.execute("INSERT INTO MOVIMENTACAO (ID_PAGADOR, ID_RECEBEDOR, VALOR, DATA_MOVIMENTACAO) VALUES (?, ?, ?, ?) RETURNING ID_MOVIMENTACAO", (id_conta, id_destino, valor, data_movimentacao))
            id_movimentacao = cursor.fetchone()[0]

            cursor.execute("UPDATE FOLHA_ITEM SET STATUS = 2, ID_MOVIMENTACAO = ?, DATA_PAGAMENTO = ? WHERE ID_FOLHA_ITEM = ? AND STATUS = 1 AND ID_MOVIMENTACAO IS NULL", (id_movimentacao, data_movimentacao, id_item))

            pagamentos.append({
                'id_item': id_item,
                'id_movimentacao': id_movimentacao,
                'valor': float(valor)
            })

        cursor.execute("SELECT COUNT(*) FROM FOLHA_ITEM WHERE ID_FOLHA = ? AND STATUS <> 2", (id_folha,))
        pendentes = cursor.fetchone()[0]

        status_folha = 3 if pendentes == 0 else 4

        cursor.execute("UPDATE FOLHA_PAGAMENTO SET STATUS = ?, DATA_PAGAMENTO = CURRENT_TIMESTAMP WHERE ID_FOLHA = ?", (status_folha, id_folha))

        con.commit()

        return jsonify({
            'mensagem': 'Folha processada com sucesso',
            'id_folha': id_folha,
            'total_pago': total,
            'quantidade_pagamentos': len(pagamentos),
            'status': status_folha,
            'pagamentos': pagamentos
        }), 200

    except Exception as e:
        con.rollback()
        return jsonify({'mensagem': 'Erro ao pagar folha', 'erro': str(e)}), 500

    finally:
        if cursor:
            cursor.close()