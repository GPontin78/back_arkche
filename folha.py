# ================================================================================
# FOLHA DE PAGAMENTO - BANCO ARKHE
# Arquivo comentado para estudo e apresentacao.
# Os comentarios explicam o codigo; nenhuma regra de negocio abaixo foi alterada.
#
# TABELAS PRINCIPAIS:
# FUNCIONARIO -> cadastro permanente da pessoa dentro da empresa.
# FOLHA_PAGAMENTO -> cabecalho da folha: empresa, mes, ano e status.
# FOLHA_ITEM -> copia/congela funcionario, CPF, salario, destino e estado naquela folha.
# MOVIMENTACAO -> transferencia financeira real criada quando o salario e pago.
# USUARIO/CONTA -> usados para descobrir a conta PF Arkhe que recebe o salario.
#
# EXEMPLO COMPLETO:
# Empresa conta 9 tem Sofia com salario R$ 2.500.
# Criar setembro/2026 gera 1 FOLHA_PAGAMENTO e 1 FOLHA_ITEM para Sofia.
# Se Sofia tem conta PF Arkhe, o item nasce STATUS=1 (pronto).
# Ao pagar, nasce MOVIMENTACAO empresa -> conta PF Sofia, e o item vira STATUS=2.
# ================================================================================

# Decimal e usado para dinheiro com precisao; ROUND_HALF_UP arredonda centavos.
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
# request le o que o front enviou; jsonify transforma respostas em JSON.
from flask import jsonify, request
# Importa a aplicacao Flask principal para registrar as rotas.
from main import app
# Importa a conexao Firebird usada para executar SQL, commit e rollback.
from banco import con
# Importa funcoes prontas de sessao, permissao, saldo, data e CPF.
from funcao import descobre_id_conta, descobre_id_usuario, usuario_pode_acessar_conta, calcular_saldo, pode_debitar_saldo, data_atual, normalizar_cpf, validar_cpf


# ================================================================
# validar_dados_funcionario(cpf, nome, salario)
# Objetivo: limpar e validar os 3 dados basicos de um funcionario.
# Exemplo: CPF='123.456.789-09', nome=' Sofia ', salario='R$ 2.500,00'.
# A funcao normaliza os valores e devolve: cpf, nome, salario, problemas.
# Se 'problemas' vier vazio, o cadastro pode continuar.
# ================================================================
def validar_dados_funcionario(cpf, nome, salario):
    # Limpa pontuacao do CPF. Ex.: 123.456.789-09 -> 12345678909.
    cpf = normalizar_cpf(cpf)
    # Garante texto e remove espacos extras do nome.
    nome = str(nome or '').strip()
    # Cria a lista que acumula todos os erros encontrados.
    problemas = []

    # CPF vazio: registra erro de campo nao informado.
    if not cpf:
        problemas.append('CPF nao informado')
    # CPF brasileiro precisa ter exatamente 11 digitos.
    elif len(cpf) != 11:
        problemas.append('CPF deve possuir 11 digitos')
    # Valida matematicamente os digitos verificadores do CPF.
    elif not validar_cpf(cpf):
        problemas.append('CPF invalido')

    # Nao permite funcionario sem nome.
    if not nome:
        problemas.append('Nome nao informado')

    # Guarda o salario como chegou, inclusive texto como R$ 2.500,00.
    salario_original = salario

    # Detecta salario ausente/vazio antes de converter.
    if salario_original is None or not str(salario_original).strip():
        salario = None
        problemas.append('Salario nao informado')
    # Caminho alternativo quando a condicao anterior nao foi atendida.
    else:
        # Inicio do bloco protegido contra erros inesperados.
        try:
            # Remove R$ e espacos para preparar a conversao.
            texto_salario = str(salario_original).strip().replace('R' + chr(36), '').replace(' ', '')
            # Converte formato brasileiro 2.500,00 para 2500.00.
            if ',' in texto_salario:
                # Remove R$ e espacos para preparar a conversao.
                texto_salario = texto_salario.replace('.', '').replace(',', '.')
            # Converte salario para Decimal com duas casas decimais.
            salario = Decimal(texto_salario).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            # Rejeita infinito, zero e valores negativos.
            if not salario.is_finite() or salario <= 0:
                # Forca o tratamento de salario invalido.
                raise ValueError()
        # Se a conversao falhar, marca o salario como invalido.
        except (InvalidOperation, TypeError, ValueError):
            salario = None
            problemas.append('Salario invalido')

    # Devolve dados tratados + lista de problemas.
    return cpf, nome, salario, problemas


# ================================================================
# contexto_folha_pj()
# Objetivo: descobrir qual conta esta usando a folha e garantir que ela e PJ.
# Exemplo: usuario logado na conta PJ 9 -> retorna (9, None).
# Se nao estiver logado, nao tiver acesso ou a conta for PF, retorna erro HTTP.
# ================================================================
def contexto_folha_pj():
    # Descobre pelo token/cookie qual pessoa esta autenticada.
    id_usuario = descobre_id_usuario()
    # Descobre qual conta esta selecionada na sessao.
    id_conta = descobre_id_conta()

    # Sem usuario ou conta autenticada, interrompe.
    if not id_usuario or not id_conta:
        # Encerra a funcao e devolve este resultado.
        return None, (jsonify({'mensagem': 'Usuario nao autenticado'}), 401)

    # Confere se o usuario pode realmente operar essa conta.
    if not usuario_pode_acessar_conta(id_usuario, id_conta):
        # Encerra a funcao e devolve este resultado.
        return None, (jsonify({'mensagem': 'Usuario sem acesso a esta conta'}), 403)

    # Abre um cursor Firebird para executar consultas SQL.
    cursor = con.cursor()
    # Consulta o tipo da conta atualmente selecionada.
    cursor.execute("SELECT TIPO_CONTA FROM CONTA WHERE ID_CONTA = ?", (id_conta,))
    # fetchone() pega somente a primeira linha da consulta anterior.
    conta = cursor.fetchone()
    # Fecha o cursor para liberar o recurso.
    cursor.close()

    # Testa esta condicao antes de continuar.
    if not conta:
        # Encerra a funcao e devolve este resultado.
        return None, (jsonify({'mensagem': 'Conta nao encontrada'}), 404)

    # TIPO_CONTA 1 = PJ; folha de pagamento e exclusiva para empresa.
    if conta[0] != 1:
        # Encerra a funcao e devolve este resultado.
        return None, (jsonify({'mensagem': 'Disponivel apenas para conta PJ'}), 403)

    # Contexto valido: devolve ID da empresa e nenhum erro.
    return id_conta, None


# Registra no Flask a rota POST /adicionar_funcionario.
# Quando o front chama esse endereco, a funcao logo abaixo e executada.
@app.route('/adicionar_funcionario', methods=['POST'])
# ================================================================
# POST /adicionar_funcionario
# Cadastra um funcionario na empresa atualmente logada.
# Exemplo recebido: {cpf: '...', nome: 'Sofia', salario: 2500}.
# Se o CPF ja for de um USUARIO Arkhe, liga o ID_USUARIO ao funcionario.
# ================================================================
def adicionar_funcionario():
    # Valida login, acesso e se a conta atual e PJ.
    id_conta, erro = contexto_folha_pj()

    # Se a validacao encontrou problema, nao continua.
    if erro:
        # Devolve ao front o erro produzido pela validacao.
        return erro

    # Le o JSON enviado pelo front.
    dados = request.get_json() or {}
    # Valida CPF, nome e salario antes de usar/gravar.
    cpf, nome, salario, problemas = validar_dados_funcionario(
        dados.get('cpf'),
        dados.get('nome'),
        dados.get('salario')
    )

    # Se existem erros de cadastro, bloqueia a operacao.
    if problemas:
        # HTTP 400: dados enviados sao invalidos/incompletos.
        return jsonify({'mensagem': '; '.join(problemas), 'erros': problemas}), 400

    # Comeca sem cursor para o finally saber se precisa fecha-lo.
    cursor = None

    # Inicio do bloco protegido contra erros inesperados.
    try:
        # Abre um cursor Firebird para executar consultas SQL.
        cursor = con.cursor()

        # Procura funcionario pelo CPF dentro desta empresa.
        cursor.execute("SELECT ID_FUNCIONARIO FROM FUNCIONARIO WHERE ID_CONTA_EMPRESA = ? AND CPF = ?", (id_conta, cpf))
        # fetchone() pega somente a primeira linha da consulta anterior.
        funcionario = cursor.fetchone()

        # Testa esta condicao antes de continuar.
        if funcionario:
            # HTTP 409: conflito, duplicidade ou estado que impede a operacao.
            return jsonify({'mensagem': 'Funcionario ja cadastrado nesta empresa'}), 409

        # Procura se ja existe um USUARIO Arkhe com esse CPF.
        cursor.execute("SELECT ID_USUARIO FROM USUARIO WHERE CPF = ?", (cpf,))
        # fetchone() pega somente a primeira linha da consulta anterior.
        usuario = cursor.fetchone()
        # Se existe usuario, guarda o ID; senao deixa None.
        id_usuario = usuario[0] if usuario else None

        # Insere o funcionario e pede ao Firebird o ID criado.
        cursor.execute("INSERT INTO FUNCIONARIO (ID_CONTA_EMPRESA, ID_USUARIO, CPF, NOME, SALARIO, STATUS) VALUES (?, ?, ?, ?, ?, 1) RETURNING ID_FUNCIONARIO", (id_conta, id_usuario, cpf, nome, salario))
        # Pega o ID_FUNCIONARIO gerado no INSERT.
        id_funcionario = cursor.fetchone()[0]

        # COMMIT confirma definitivamente as alteracoes no Firebird.
        con.commit()

        # Monta a resposta JSON que sera enviada ao front.
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

    # Captura erro inesperado para responder sem derrubar a API.
    except Exception as e:
        # ROLLBACK desfaz alteracoes ainda nao confirmadas.
        con.rollback()
        # HTTP 500: erro inesperado no servidor.
        return jsonify({'mensagem': 'Erro ao cadastrar funcionario', 'erro': str(e)}), 500

    # Roda sempre, com sucesso ou erro.
    finally:
        # So fecha se o cursor realmente foi criado.
        if cursor:
            # Fecha o cursor para liberar o recurso.
            cursor.close()


# Registra no Flask a rota GET /listar_funcionarios.
# Quando o front chama esse endereco, a funcao logo abaixo e executada.
@app.route('/listar_funcionarios', methods=['GET'])
# ================================================================
# GET /listar_funcionarios
# Lista os funcionarios da empresa atual e tenta localizar a conta PF Arkhe.
# Cadastros antigos invalidos continuam aparecendo, marcados cadastro_valido=False.
# ================================================================
def listar_funcionarios():
    # Valida login, acesso e se a conta atual e PJ.
    id_conta, erro = contexto_folha_pj()

    # Se a validacao encontrou problema, nao continua.
    if erro:
        # Devolve ao front o erro produzido pela validacao.
        return erro

    # Comeca sem cursor para o finally saber se precisa fecha-lo.
    cursor = None

    # Inicio do bloco protegido contra erros inesperados.
    try:
        # Abre um cursor Firebird para executar consultas SQL.
        cursor = con.cursor()

        # Consulta funcionarios e junta, quando existir, a conta PF Arkhe.
        cursor.execute("SELECT F.ID_FUNCIONARIO, F.ID_USUARIO, F.CPF, F.NOME, F.SALARIO, F.STATUS, F.DATA_CADASTRO, C.ID_CONTA FROM FUNCIONARIO F LEFT JOIN CONTA C ON C.ID_USUARIO = F.ID_USUARIO AND C.TIPO_CONTA = 0 WHERE F.ID_CONTA_EMPRESA = ? ORDER BY F.STATUS DESC, F.NOME", (id_conta,))
        # fetchall() pega todas as linhas retornadas.
        dados = cursor.fetchall()

        # Lista que sera preenchida e enviada ao front.
        funcionarios = []

        # Percorre os funcionarios retornados pelo banco.
        for funcionario in dados:
            # Valida CPF, nome e salario antes de usar/gravar.
            cpf, nome, salario, problemas = validar_dados_funcionario(
                funcionario[2],
                funcionario[3],
                funcionario[4]
            )

            # Adiciona este funcionario ao JSON final.
            funcionarios.append({
                'id_funcionario': funcionario[0],
                'id_usuario': funcionario[1],
                'cpf': cpf,
                'nome': nome,
                'salario': float(salario) if salario is not None else None,
                'status': funcionario[5],
                'data_cadastro': str(funcionario[6]) if funcionario[6] else None,
                'id_conta_pf': funcionario[7],
                'possui_conta_arkhe': funcionario[7] is not None,
                'cadastro_valido': len(problemas) == 0,
                'erros_cadastro': problemas
            })

        # Envia a lista de funcionarios ao front com sucesso.
        return jsonify(funcionarios), 200

    # Captura erro inesperado para responder sem derrubar a API.
    except Exception as e:
        # HTTP 500: erro inesperado no servidor.
        return jsonify({'mensagem': 'Erro ao listar funcionarios', 'erro': str(e)}), 500

    # Roda sempre, com sucesso ou erro.
    finally:
        # So fecha se o cursor realmente foi criado.
        if cursor:
            # Fecha o cursor para liberar o recurso.
            cursor.close()


# Registra no Flask a rota PUT /editar_funcionario.
# Quando o front chama esse endereco, a funcao logo abaixo e executada.
@app.route('/editar_funcionario', methods=['PUT'])
# ================================================================
# PUT /editar_funcionario
# Atualiza CPF, nome e salario e refaz o vinculo com USUARIO Arkhe pelo CPF.
# Tambem impede CPF repetido entre funcionarios da mesma empresa.
# ================================================================
def editar_funcionario():
    # Valida login, acesso e se a conta atual e PJ.
    id_conta, erro = contexto_folha_pj()

    # Se a validacao encontrou problema, nao continua.
    if erro:
        # Devolve ao front o erro produzido pela validacao.
        return erro

    # Le o JSON enviado pelo front.
    dados = request.get_json() or {}
    # Le do JSON qual funcionario sera alterado.
    id_funcionario = dados.get('id_funcionario')

    # Sem ID nao ha como saber qual funcionario alterar.
    if not id_funcionario:
        # HTTP 400: dados enviados sao invalidos/incompletos.
        return jsonify({'mensagem': 'Funcionario nao informado'}), 400

    # Comeca sem cursor para o finally saber se precisa fecha-lo.
    cursor = None

    # Inicio do bloco protegido contra erros inesperados.
    try:
        # Abre um cursor Firebird para executar consultas SQL.
        cursor = con.cursor()

        # Executa a consulta SQL abaixo; os '?' recebem os parametros separadamente.
        cursor.execute(
            "SELECT CPF FROM FUNCIONARIO WHERE ID_FUNCIONARIO = ? AND ID_CONTA_EMPRESA = ?",
            (id_funcionario, id_conta)
        )
        # fetchone() pega somente a primeira linha da consulta anterior.
        atual = cursor.fetchone()

        # Testa esta condicao antes de continuar.
        if not atual:
            # HTTP 404: registro nao encontrado.
            return jsonify({'mensagem': 'Funcionario nao encontrado'}), 404

        # Valida CPF, nome e salario antes de usar/gravar.
        cpf, nome, salario, problemas = validar_dados_funcionario(
            dados.get('cpf', atual[0]),
            dados.get('nome'),
            dados.get('salario')
        )

        # Se existem erros de cadastro, bloqueia a operacao.
        if problemas:
            # HTTP 400: dados enviados sao invalidos/incompletos.
            return jsonify({'mensagem': '; '.join(problemas), 'erros': problemas}), 400

        # Procura funcionario pelo CPF dentro desta empresa.
        cursor.execute(
            "SELECT ID_FUNCIONARIO FROM FUNCIONARIO WHERE ID_CONTA_EMPRESA = ? AND CPF = ? AND ID_FUNCIONARIO <> ?",
            (id_conta, cpf, id_funcionario)
        )

        # Se encontrou uma linha, existe conflito/duplicidade.
        if cursor.fetchone():
            # HTTP 409: conflito, duplicidade ou estado que impede a operacao.
            return jsonify({'mensagem': 'CPF ja cadastrado para outro funcionario desta empresa'}), 409

        # Procura se ja existe um USUARIO Arkhe com esse CPF.
        cursor.execute("SELECT ID_USUARIO FROM USUARIO WHERE CPF = ?", (cpf,))
        # fetchone() pega somente a primeira linha da consulta anterior.
        usuario = cursor.fetchone()
        # Se existe usuario, guarda o ID; senao deixa None.
        id_usuario = usuario[0] if usuario else None

        # Atualiza dados do funcionario.
        cursor.execute(
            """UPDATE FUNCIONARIO
               SET CPF = ?, NOME = ?, SALARIO = ?, ID_USUARIO = ?
               WHERE ID_FUNCIONARIO = ? AND ID_CONTA_EMPRESA = ?""",
            (cpf, nome, salario, id_usuario, id_funcionario, id_conta)
        )

        # COMMIT confirma definitivamente as alteracoes no Firebird.
        con.commit()

        # Monta a resposta JSON que sera enviada ao front.
        return jsonify({
            'mensagem': 'Funcionario atualizado com sucesso',
            'cpf': cpf,
            'nome': nome,
            'salario': float(salario),
            'id_usuario': id_usuario,
            'cadastro_valido': True,
            'erros_cadastro': []
        }), 200

    # Captura erro inesperado para responder sem derrubar a API.
    except Exception as e:
        # ROLLBACK desfaz alteracoes ainda nao confirmadas.
        con.rollback()
        # HTTP 500: erro inesperado no servidor.
        return jsonify({'mensagem': 'Erro ao editar funcionario', 'erro': str(e)}), 500

    # Roda sempre, com sucesso ou erro.
    finally:
        # So fecha se o cursor realmente foi criado.
        if cursor:
            # Fecha o cursor para liberar o recurso.
            cursor.close()


# Registra no Flask a rota PUT /alterar_status_funcionario.
# Quando o front chama esse endereco, a funcao logo abaixo e executada.
@app.route('/alterar_status_funcionario', methods=['PUT'])
# ================================================================
# PUT /alterar_status_funcionario
# Ativa (1) ou inativa (0) um funcionario.
# Funcionario inativo permanece salvo, mas nao entra em novas folhas.
# ================================================================
def alterar_status_funcionario():
    # Valida login, acesso e se a conta atual e PJ.
    id_conta, erro = contexto_folha_pj()

    # Se a validacao encontrou problema, nao continua.
    if erro:
        # Devolve ao front o erro produzido pela validacao.
        return erro

    # Le o JSON enviado pelo front.
    dados = request.get_json() or {}
    # Le do JSON qual funcionario sera alterado.
    id_funcionario = dados.get('id_funcionario')

    # Inicio do bloco protegido contra erros inesperados.
    try:
        # Converte status para inteiro: 0=inativo, 1=ativo.
        status = int(dados.get('status'))
    # Valor de status que nao vira inteiro e invalido.
    except (TypeError, ValueError):
        # HTTP 400: dados enviados sao invalidos/incompletos.
        return jsonify({'mensagem': 'Status invalido'}), 400

    # Sem ID nao ha como saber qual funcionario alterar.
    if not id_funcionario or status not in (0, 1):
        # HTTP 400: dados enviados sao invalidos/incompletos.
        return jsonify({'mensagem': 'Dados incompletos'}), 400

    # Comeca sem cursor para o finally saber se precisa fecha-lo.
    cursor = None

    # Inicio do bloco protegido contra erros inesperados.
    try:
        # Abre um cursor Firebird para executar consultas SQL.
        cursor = con.cursor()

        # Executa a consulta SQL abaixo; os '?' recebem os parametros separadamente.
        cursor.execute(
            "SELECT CPF, NOME, SALARIO FROM FUNCIONARIO WHERE ID_FUNCIONARIO = ? AND ID_CONTA_EMPRESA = ?",
            (id_funcionario, id_conta)
        )
        # fetchone() pega somente a primeira linha da consulta anterior.
        funcionario = cursor.fetchone()

        # Testa esta condicao antes de continuar.
        if not funcionario:
            # HTTP 404: registro nao encontrado.
            return jsonify({'mensagem': 'Funcionario nao encontrado'}), 404

        # Antes de reativar, valida novamente o cadastro.
        if status == 1:
            _cpf, _nome, _salario, problemas = validar_dados_funcionario(
                funcionario[0], funcionario[1], funcionario[2]
            )

            # Se existem erros de cadastro, bloqueia a operacao.
            if problemas:
                # Monta a resposta JSON que sera enviada ao front.
                return jsonify({
                    'mensagem': 'Corrija o cadastro antes de reativar o funcionario',
                    'erros': problemas
                }), 400

        # Atualiza dados do funcionario.
        cursor.execute(
            "UPDATE FUNCIONARIO SET STATUS = ? WHERE ID_FUNCIONARIO = ? AND ID_CONTA_EMPRESA = ?",
            (status, id_funcionario, id_conta)
        )

        # COMMIT confirma definitivamente as alteracoes no Firebird.
        con.commit()

        # Monta a resposta JSON que sera enviada ao front.
        return jsonify({'mensagem': 'Status alterado com sucesso'}), 200

    # Captura erro inesperado para responder sem derrubar a API.
    except Exception as e:
        # ROLLBACK desfaz alteracoes ainda nao confirmadas.
        con.rollback()
        # HTTP 500: erro inesperado no servidor.
        return jsonify({'mensagem': 'Erro ao alterar status', 'erro': str(e)}), 500

    # Roda sempre, com sucesso ou erro.
    finally:
        # So fecha se o cursor realmente foi criado.
        if cursor:
            # Fecha o cursor para liberar o recurso.
            cursor.close()

# Registra no Flask a rota POST /criar_folha.
# Quando o front chama esse endereco, a funcao logo abaixo e executada.
@app.route('/criar_folha', methods=['POST'])
# ================================================================
# POST /criar_folha
# Cria a folha de uma competencia, por exemplo setembro/2026.
# Fluxo: confere duplicidade -> pega ativos -> valida -> procura conta PF -> cria itens.
# STATUS FOLHA_ITEM aqui: 1 = pronto para pagar; 0 = pendente sem conta PF.
# ================================================================
def criar_folha():
    # Valida login, acesso e se a conta atual e PJ.
    id_conta, erro = contexto_folha_pj()

    # Se a validacao encontrou problema, nao continua.
    if erro:
        # Devolve ao front o erro produzido pela validacao.
        return erro

    # Le o JSON enviado pelo front.
    dados = request.get_json()
    # Le o mes da competencia. Ex.: 9 = setembro.
    mes = dados.get('mes')
    # Le o ano da competencia. Ex.: 2026.
    ano = dados.get('ano')

    # Folha exige mes e ano.
    if not mes or not ano:
        # HTTP 400: dados enviados sao invalidos/incompletos.
        return jsonify({'mensagem': 'Mes e ano nao informados'}), 400

    # Comeca sem cursor para o finally saber se precisa fecha-lo.
    cursor = None

    # Inicio do bloco protegido contra erros inesperados.
    try:
        # Abre um cursor Firebird para executar consultas SQL.
        cursor = con.cursor()

        # Busca somente funcionarios ativos para participar da folha.
        cursor.execute("SELECT ID_FOLHA FROM FOLHA_PAGAMENTO WHERE ID_CONTA_EMPRESA = ? AND COMPETENCIA_MES = ? AND COMPETENCIA_ANO = ?", (id_conta, mes, ano))
        # fetchone() pega somente a primeira linha da consulta anterior.
        folha_existente = cursor.fetchone()

        # Impede duas folhas para a mesma empresa/mes/ano.
        if folha_existente:
            # HTTP 409: conflito, duplicidade ou estado que impede a operacao.
            return jsonify({'mensagem': 'Ja existe uma folha para esta competencia', 'id_folha': folha_existente[0]}), 409

        # Busca somente funcionarios ativos para participar da folha.
        cursor.execute("SELECT ID_FUNCIONARIO, CPF, NOME, SALARIO FROM FUNCIONARIO WHERE ID_CONTA_EMPRESA = ? AND STATUS = 1 ORDER BY NOME", (id_conta,))
        # fetchall() pega todas as linhas retornadas.
        funcionarios = cursor.fetchall()

        # Lista temporaria dos cadastros aprovados.
        funcionarios_validos = []
        # Lista temporaria dos cadastros que precisam de correcao.
        funcionarios_invalidos = []

        # Valida cada funcionario antes de montar a folha.
        for funcionario in funcionarios:
            _cpf, _nome, _salario, problemas = validar_dados_funcionario(
                funcionario[1], funcionario[2], funcionario[3]
            )
            # Se existem erros de cadastro, bloqueia a operacao.
            if problemas:
                # Guarda quem esta invalido e quais erros possui.
                funcionarios_invalidos.append({
                    'id_funcionario': funcionario[0],
                    'cpf': normalizar_cpf(funcionario[1]),
                    'erros': problemas
                })
            # Caminho alternativo quando a condicao anterior nao foi atendida.
            else:
                # Adiciona cadastro aprovado a lista valida.
                funcionarios_validos.append(funcionario)

        # Se existe ativo invalido, bloqueia criacao/edicao da folha.
        if funcionarios_invalidos:
            # Monta a resposta JSON que sera enviada ao front.
            return jsonify({
                'mensagem': 'Existem funcionarios ativos com cadastro invalido. Corrija-os antes de criar a folha.',
                'funcionarios_invalidos': funcionarios_invalidos
            }), 400

        # Daqui em diante usa somente os funcionarios aprovados.
        funcionarios = funcionarios_validos

        # Nao gera folha vazia.
        if not funcionarios:
            # HTTP 400: dados enviados sao invalidos/incompletos.
            return jsonify({'mensagem': 'Nenhum funcionario ativo cadastrado'}), 400

        # Procura pelo CPF uma conta PF Arkhe que possa receber o salario.
        cursor.execute("INSERT INTO FOLHA_PAGAMENTO (ID_CONTA_EMPRESA, COMPETENCIA_MES, COMPETENCIA_ANO, STATUS) VALUES (?, ?, ?, 0) RETURNING ID_FOLHA", (id_conta, mes, ano))
        # Pega o ID da nova folha criado pelo Firebird.
        id_folha = cursor.fetchone()[0]

        # Valida cada funcionario antes de montar a folha.
        for funcionario in funcionarios:
            # Coluna 0 = ID_FUNCIONARIO.
            id_funcionario = funcionario[0]
            # Coluna 1 = CPF.
            cpf = funcionario[1]
            # Coluna 2 = nome.
            nome = funcionario[2]
            # Coluna 3 = salario que sera congelado no item.
            salario = funcionario[3]

            # Procura pelo CPF uma conta PF Arkhe que possa receber o salario.
            cursor.execute("""SELECT C.ID_CONTA FROM USUARIO U INNER JOIN CONTA C ON C.ID_USUARIO = U.ID_USUARIO WHERE U.CPF = ? AND C.TIPO_CONTA = 0 ORDER BY C.ID_CONTA ROWS 1""", (cpf,))
            # fetchone() pega somente a primeira linha da consulta anterior.
            conta_pf = cursor.fetchone()

            # Se encontrou conta PF, o item ja pode ficar pronto.
            if conta_pf:
                # ID da conta PF que recebera o salario.
                id_conta_destino = conta_pf[0]
                # STATUS 1 no item = pronto para pagamento.
                status = 1
                # Sem erro porque a conta de destino foi localizada.
                erro_item = None
            # Caminho alternativo quando a condicao anterior nao foi atendida.
            else:
                # Sem conta PF, ainda nao existe destino para o salario.
                id_conta_destino = None
                # STATUS 0 no item = pendente.
                status = 0
                # Motivo da pendencia mostrado ao usuario.
                erro_item = 'Conta PF Arkhe nao encontrada'

            # Cria o item da folha, congelando funcionario, salario e destino.
            cursor.execute("INSERT INTO FOLHA_ITEM (ID_FOLHA, ID_FUNCIONARIO, ID_CONTA_DESTINO, CPF, NOME, VALOR, STATUS, ERRO) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (id_folha, id_funcionario, id_conta_destino, cpf, nome, salario, status, erro_item))

        # COMMIT confirma definitivamente as alteracoes no Firebird.
        con.commit()

        # Monta a resposta JSON que sera enviada ao front.
        return jsonify({
            'mensagem': 'Folha criada com sucesso',
            'id_folha': id_folha
        }), 201

    # Captura erro inesperado para responder sem derrubar a API.
    except Exception as e:
        # ROLLBACK desfaz alteracoes ainda nao confirmadas.
        con.rollback()
        # HTTP 500: erro inesperado no servidor.
        return jsonify({'mensagem': 'Erro ao criar folha', 'erro': str(e)}), 500

    # Roda sempre, com sucesso ou erro.
    finally:
        # So fecha se o cursor realmente foi criado.
        if cursor:
            # Fecha o cursor para liberar o recurso.
            cursor.close()


# Registra no Flask a rota PUT /editar_folha.
# Quando o front chama esse endereco, a funcao logo abaixo e executada.
@app.route('/editar_folha', methods=['PUT'])
# ================================================================
# PUT /editar_folha
# Edita apenas rascunho e reconstroi os itens com os funcionarios ativos atuais.
# Nao permite editar folha que ja tenha movimentacao financeira.
# ================================================================
def editar_folha():
    # Valida login, acesso e se a conta atual e PJ.
    id_conta, erro = contexto_folha_pj()

    # Se a validacao encontrou problema, nao continua.
    if erro:
        # Devolve ao front o erro produzido pela validacao.
        return erro

    # Le o JSON enviado pelo front.
    dados = request.get_json() or {}
    # Le do JSON qual folha sera manipulada.
    id_folha = dados.get('id_folha')
    # Le o mes da competencia. Ex.: 9 = setembro.
    mes = dados.get('mes')
    # Le o ano da competencia. Ex.: 2026.
    ano = dados.get('ano')

    # Sem ID_FOLHA nao ha como revalidar ou pagar.
    if not id_folha or not mes or not ano:
        # HTTP 400: dados enviados sao invalidos/incompletos.
        return jsonify({'mensagem': 'Folha, mes e ano sao obrigatorios'}), 400

    # Inicio do bloco protegido contra erros inesperados.
    try:
        # Converte mes para numero inteiro.
        mes = int(mes)
        # Converte ano para numero inteiro.
        ano = int(ano)
    except Exception:
        # HTTP 400: dados enviados sao invalidos/incompletos.
        return jsonify({'mensagem': 'Mes ou ano invalido'}), 400

    # Valida intervalo de competencia.
    if mes < 1 or mes > 12 or ano < 2000 or ano > 2200:
        # HTTP 400: dados enviados sao invalidos/incompletos.
        return jsonify({'mensagem': 'Competencia invalida'}), 400

    # Comeca sem cursor para o finally saber se precisa fecha-lo.
    cursor = None

    # Inicio do bloco protegido contra erros inesperados.
    try:
        # Abre um cursor Firebird para executar consultas SQL.
        cursor = con.cursor()

        # Busca a folha desta empresa e le seu status.
        cursor.execute("SELECT STATUS FROM FOLHA_PAGAMENTO WHERE ID_FOLHA = ? AND ID_CONTA_EMPRESA = ?", (id_folha, id_conta))
        # fetchone() pega somente a primeira linha da consulta anterior.
        folha = cursor.fetchone()

        # Testa esta condicao antes de continuar.
        if not folha:
            # HTTP 404: registro nao encontrado.
            return jsonify({'mensagem': 'Folha nao encontrada'}), 404

        # So STATUS 0 (rascunho) pode ser editado/excluido.
        if folha[0] != 0:
            # HTTP 409: conflito, duplicidade ou estado que impede a operacao.
            return jsonify({'mensagem': 'Somente folhas em rascunho podem ser editadas'}), 409

        # Busca somente funcionarios ativos para participar da folha.
        cursor.execute("SELECT COUNT(*) FROM FOLHA_ITEM WHERE ID_FOLHA = ? AND ID_MOVIMENTACAO IS NOT NULL", (id_folha,))
        # Se ja existe movimentacao, nao permite alterar/excluir.
        if cursor.fetchone()[0] > 0:
            # HTTP 409: conflito, duplicidade ou estado que impede a operacao.
            return jsonify({'mensagem': 'Esta folha possui movimentacoes e nao pode ser editada'}), 409

        # Busca somente funcionarios ativos para participar da folha.
        cursor.execute("SELECT ID_FOLHA FROM FOLHA_PAGAMENTO WHERE ID_CONTA_EMPRESA = ? AND COMPETENCIA_MES = ? AND COMPETENCIA_ANO = ? AND ID_FOLHA <> ?", (id_conta, mes, ano, id_folha))
        # fetchone() pega somente a primeira linha da consulta anterior.
        existente = cursor.fetchone()

        # Impede competencia duplicada.
        if existente:
            # HTTP 409: conflito, duplicidade ou estado que impede a operacao.
            return jsonify({'mensagem': 'Ja existe uma folha para esta competencia', 'id_folha': existente[0]}), 409

        # Busca somente funcionarios ativos para participar da folha.
        cursor.execute("SELECT ID_FUNCIONARIO, CPF, NOME, SALARIO FROM FUNCIONARIO WHERE ID_CONTA_EMPRESA = ? AND STATUS = 1 ORDER BY NOME", (id_conta,))
        # fetchall() pega todas as linhas retornadas.
        funcionarios = cursor.fetchall()

        # Lista temporaria dos cadastros que precisam de correcao.
        funcionarios_invalidos = []

        # Valida cada funcionario antes de montar a folha.
        for funcionario in funcionarios:
            _cpf, _nome, _salario, problemas = validar_dados_funcionario(
                funcionario[1], funcionario[2], funcionario[3]
            )
            # Se existem erros de cadastro, bloqueia a operacao.
            if problemas:
                # Guarda quem esta invalido e quais erros possui.
                funcionarios_invalidos.append({
                    'id_funcionario': funcionario[0],
                    'cpf': normalizar_cpf(funcionario[1]),
                    'erros': problemas
                })

        # Se existe ativo invalido, bloqueia criacao/edicao da folha.
        if funcionarios_invalidos:
            # Monta a resposta JSON que sera enviada ao front.
            return jsonify({
                'mensagem': 'Existem funcionarios ativos com cadastro invalido. Corrija-os antes de atualizar a folha.',
                'funcionarios_invalidos': funcionarios_invalidos
            }), 400

        # Nao gera folha vazia.
        if not funcionarios:
            # HTTP 400: dados enviados sao invalidos/incompletos.
            return jsonify({'mensagem': 'Nenhum funcionario ativo cadastrado'}), 400

        # Procura pelo CPF uma conta PF Arkhe que possa receber o salario.
        cursor.execute("DELETE FROM FOLHA_ITEM WHERE ID_FOLHA = ?", (id_folha,))
        # Procura pelo CPF uma conta PF Arkhe que possa receber o salario.
        cursor.execute("UPDATE FOLHA_PAGAMENTO SET COMPETENCIA_MES = ?, COMPETENCIA_ANO = ?, STATUS = 0, DATA_PAGAMENTO = NULL WHERE ID_FOLHA = ? AND ID_CONTA_EMPRESA = ?", (mes, ano, id_folha, id_conta))

        # Valida cada funcionario antes de montar a folha.
        for funcionario in funcionarios:
            # Coluna 0 = ID_FUNCIONARIO.
            id_funcionario = funcionario[0]
            # Coluna 1 = CPF.
            cpf = funcionario[1]
            # Coluna 2 = nome.
            nome = funcionario[2]
            # Coluna 3 = salario que sera congelado no item.
            salario = funcionario[3]

            # Procura pelo CPF uma conta PF Arkhe que possa receber o salario.
            cursor.execute("""SELECT C.ID_CONTA FROM USUARIO U INNER JOIN CONTA C ON C.ID_USUARIO = U.ID_USUARIO WHERE U.CPF = ? AND C.TIPO_CONTA = 0 ORDER BY C.ID_CONTA ROWS 1""", (cpf,))
            # fetchone() pega somente a primeira linha da consulta anterior.
            conta_pf = cursor.fetchone()

            # Se encontrou conta PF, o item ja pode ficar pronto.
            if conta_pf:
                # ID da conta PF que recebera o salario.
                id_conta_destino = conta_pf[0]
                # STATUS 1 no item = pronto para pagamento.
                status = 1
                # Sem erro porque a conta de destino foi localizada.
                erro_item = None
            # Caminho alternativo quando a condicao anterior nao foi atendida.
            else:
                # Sem conta PF, ainda nao existe destino para o salario.
                id_conta_destino = None
                # STATUS 0 no item = pendente.
                status = 0
                # Motivo da pendencia mostrado ao usuario.
                erro_item = 'Conta PF Arkhe nao encontrada'

            # Cria o item da folha, congelando funcionario, salario e destino.
            cursor.execute("INSERT INTO FOLHA_ITEM (ID_FOLHA, ID_FUNCIONARIO, ID_CONTA_DESTINO, CPF, NOME, VALOR, STATUS, ERRO) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (id_folha, id_funcionario, id_conta_destino, cpf, nome, salario, status, erro_item))

        # COMMIT confirma definitivamente as alteracoes no Firebird.
        con.commit()

        # Monta a resposta JSON que sera enviada ao front.
        return jsonify({'mensagem': 'Rascunho atualizado com sucesso', 'id_folha': id_folha}), 200

    # Captura erro inesperado para responder sem derrubar a API.
    except Exception as e:
        # ROLLBACK desfaz alteracoes ainda nao confirmadas.
        con.rollback()
        # HTTP 500: erro inesperado no servidor.
        return jsonify({'mensagem': 'Erro ao editar folha', 'erro': str(e)}), 500

    # Roda sempre, com sucesso ou erro.
    finally:
        # So fecha se o cursor realmente foi criado.
        if cursor:
            # Fecha o cursor para liberar o recurso.
            cursor.close()


# Registra no Flask a rota DELETE /folha/<int:id_folha>.
# Quando o front chama esse endereco, a funcao logo abaixo e executada.
@app.route('/folha/<int:id_folha>', methods=['DELETE'])
# ================================================================
# DELETE /folha/<id_folha>
# Exclui somente rascunho sem movimentacoes: primeiro itens, depois cabecalho.
# ================================================================
def excluir_folha(id_folha):
    # Valida login, acesso e se a conta atual e PJ.
    id_conta, erro = contexto_folha_pj()

    # Se a validacao encontrou problema, nao continua.
    if erro:
        # Devolve ao front o erro produzido pela validacao.
        return erro

    # Comeca sem cursor para o finally saber se precisa fecha-lo.
    cursor = None

    # Inicio do bloco protegido contra erros inesperados.
    try:
        # Abre um cursor Firebird para executar consultas SQL.
        cursor = con.cursor()

        # Apaga os itens atuais da folha.
        cursor.execute("SELECT STATUS FROM FOLHA_PAGAMENTO WHERE ID_FOLHA = ? AND ID_CONTA_EMPRESA = ?", (id_folha, id_conta))
        # fetchone() pega somente a primeira linha da consulta anterior.
        folha = cursor.fetchone()

        # Testa esta condicao antes de continuar.
        if not folha:
            # HTTP 404: registro nao encontrado.
            return jsonify({'mensagem': 'Folha nao encontrada'}), 404

        # So STATUS 0 (rascunho) pode ser editado/excluido.
        if folha[0] != 0:
            # HTTP 409: conflito, duplicidade ou estado que impede a operacao.
            return jsonify({'mensagem': 'Somente folhas em rascunho podem ser excluidas'}), 409

        # Apaga os itens atuais da folha.
        cursor.execute("SELECT COUNT(*) FROM FOLHA_ITEM WHERE ID_FOLHA = ? AND ID_MOVIMENTACAO IS NOT NULL", (id_folha,))
        # Se ja existe movimentacao, nao permite alterar/excluir.
        if cursor.fetchone()[0] > 0:
            # HTTP 409: conflito, duplicidade ou estado que impede a operacao.
            return jsonify({'mensagem': 'Esta folha possui movimentacoes e nao pode ser excluida'}), 409

        # Apaga os itens atuais da folha.
        cursor.execute("DELETE FROM FOLHA_ITEM WHERE ID_FOLHA = ?", (id_folha,))
        # Apaga o cabecalho da folha.
        cursor.execute("DELETE FROM FOLHA_PAGAMENTO WHERE ID_FOLHA = ? AND ID_CONTA_EMPRESA = ?", (id_folha, id_conta))

        # COMMIT confirma definitivamente as alteracoes no Firebird.
        con.commit()

        # Monta a resposta JSON que sera enviada ao front.
        return jsonify({'mensagem': 'Rascunho excluido com sucesso', 'id_folha': id_folha}), 200

    # Captura erro inesperado para responder sem derrubar a API.
    except Exception as e:
        # ROLLBACK desfaz alteracoes ainda nao confirmadas.
        con.rollback()
        # HTTP 500: erro inesperado no servidor.
        return jsonify({'mensagem': 'Erro ao excluir folha', 'erro': str(e)}), 500

    # Roda sempre, com sucesso ou erro.
    finally:
        # So fecha se o cursor realmente foi criado.
        if cursor:
            # Fecha o cursor para liberar o recurso.
            cursor.close()


# Registra no Flask a rota GET /listar_folhas.
# Quando o front chama esse endereco, a funcao logo abaixo e executada.
@app.route('/listar_folhas', methods=['GET'])
# ================================================================
# GET /listar_folhas
# Monta o historico de folhas e agrega valores/quantidades por status.
# ================================================================
def listar_folhas():
    # Valida login, acesso e se a conta atual e PJ.
    id_conta, erro = contexto_folha_pj()

    # Se a validacao encontrou problema, nao continua.
    if erro:
        # Devolve ao front o erro produzido pela validacao.
        return erro

    # Comeca sem cursor para o finally saber se precisa fecha-lo.
    cursor = None

    # Inicio do bloco protegido contra erros inesperados.
    try:
        # Abre um cursor Firebird para executar consultas SQL.
        cursor = con.cursor()

        # Busca o historico e calcula totais/quantidades agrupados por folha.
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

        # fetchall() pega todas as linhas retornadas.
        dados = cursor.fetchall()
        # Lista final do historico.
        folhas = []

        # Converte cada linha SQL em objeto JSON.
        for folha in dados:
            # Adiciona o resumo desta folha na lista.
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

        # Monta a resposta JSON que sera enviada ao front.
        return jsonify({'folhas': folhas, 'total': len(folhas)}), 200

    # Captura erro inesperado para responder sem derrubar a API.
    except Exception as e:
        # HTTP 500: erro inesperado no servidor.
        return jsonify({'mensagem': 'Erro ao listar folhas', 'erro': str(e)}), 500

    # Roda sempre, com sucesso ou erro.
    finally:
        # So fecha se o cursor realmente foi criado.
        if cursor:
            # Fecha o cursor para liberar o recurso.
            cursor.close()


# Registra no Flask a rota GET /folha/<int:id_folha>.
# Quando o front chama esse endereco, a funcao logo abaixo e executada.
@app.route('/folha/<int:id_folha>', methods=['GET'])
# ================================================================
# GET /folha/<id_folha>
# Busca uma folha especifica, seus itens e calcula os totais da previa.
# ================================================================
def buscar_folha(id_folha):
    # Valida login, acesso e se a conta atual e PJ.
    id_conta, erro = contexto_folha_pj()

    # Se a validacao encontrou problema, nao continua.
    if erro:
        # Devolve ao front o erro produzido pela validacao.
        return erro

    # Comeca sem cursor para o finally saber se precisa fecha-lo.
    cursor = None

    # Inicio do bloco protegido contra erros inesperados.
    try:
        # Abre um cursor Firebird para executar consultas SQL.
        cursor = con.cursor()

        # Busca a folha desta empresa e le seu status.
        cursor.execute("SELECT ID_FOLHA, COMPETENCIA_MES, COMPETENCIA_ANO, STATUS, DATA_CRIACAO, DATA_PAGAMENTO FROM FOLHA_PAGAMENTO WHERE ID_FOLHA = ? AND ID_CONTA_EMPRESA = ?", (id_folha, id_conta))
        # fetchone() pega somente a primeira linha da consulta anterior.
        folha = cursor.fetchone()

        # Testa esta condicao antes de continuar.
        if not folha:
            # HTTP 404: registro nao encontrado.
            return jsonify({'mensagem': 'Folha nao encontrada'}), 404

        # Busca os itens que pertencem a esta folha.
        cursor.execute("SELECT ID_FOLHA_ITEM, ID_FUNCIONARIO, ID_CONTA_DESTINO, CPF, NOME, VALOR, STATUS, ERRO, ID_MOVIMENTACAO, DATA_PAGAMENTO FROM FOLHA_ITEM WHERE ID_FOLHA = ? ORDER BY NOME", (id_folha,))
        # fetchall() pega todas as linhas retornadas.
        dados = cursor.fetchall()

        # Lista detalhada dos itens/funcionarios da folha.
        itens = []
        # Soma geral de todos os salarios da folha.
        total = 0
        # Soma dos itens prontos para pagamento.
        total_valido = 0
        # Soma dos itens pendentes.
        total_pendente = 0
        # Soma dos itens pagos.
        total_pago = 0
        # Contador de itens prontos.
        quantidade_validos = 0
        # Contador de itens pendentes.
        quantidade_pendentes = 0
        # Contador de itens pagos.
        quantidade_pagos = 0

        # Percorre cada item para calcular totais e montar a resposta.
        for item in dados:
            # Converte o valor do banco para numero JSON.
            valor = float(item[5])
            # Soma este salario ao total geral.
            total += valor

            # STATUS 1 = pronto para pagar.
            if item[6] == 1:
                # Soma o valor ao acumulador correspondente.
                total_valido += valor
                # Incrementa o contador correspondente.
                quantidade_validos += 1

            # STATUS 0 = pendente.
            if item[6] == 0:
                # Soma o valor ao acumulador correspondente.
                total_pendente += valor
                # Incrementa o contador correspondente.
                quantidade_pendentes += 1

            # STATUS 2 = pago.
            if item[6] == 2:
                # Soma o valor ao acumulador correspondente.
                total_pago += valor
                # Incrementa o contador correspondente.
                quantidade_pagos += 1

            # Adiciona este item na resposta detalhada.
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

        # Monta a resposta JSON que sera enviada ao front.
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

    # Captura erro inesperado para responder sem derrubar a API.
    except Exception as e:
        # HTTP 500: erro inesperado no servidor.
        return jsonify({'mensagem': 'Erro ao buscar folha', 'erro': str(e)}), 500

    # Roda sempre, com sucesso ou erro.
    finally:
        # So fecha se o cursor realmente foi criado.
        if cursor:
            # Fecha o cursor para liberar o recurso.
            cursor.close()
# Registra no Flask a rota POST /revalidar_folha.
# Quando o front chama esse endereco, a funcao logo abaixo e executada.
@app.route('/revalidar_folha', methods=['POST'])
# ================================================================
# POST /revalidar_folha
# Tenta resolver pendencias de quem antes nao tinha conta PF Arkhe.
# Exemplo: Sofia abriu conta PF depois da folha ser criada; revalidar encontra e libera.
# ================================================================
def revalidar_folha():
    # Valida login, acesso e se a conta atual e PJ.
    id_conta, erro = contexto_folha_pj()

    # Se a validacao encontrou problema, nao continua.
    if erro:
        # Devolve ao front o erro produzido pela validacao.
        return erro

    # Le o JSON enviado pelo front.
    dados = request.get_json()
    # Le do JSON qual folha sera manipulada.
    id_folha = dados.get('id_folha')

    # Sem ID_FOLHA nao ha como revalidar ou pagar.
    if not id_folha:
        # HTTP 400: dados enviados sao invalidos/incompletos.
        return jsonify({'mensagem': 'Folha nao informada'}), 400

    # Comeca sem cursor para o finally saber se precisa fecha-lo.
    cursor = None

    # Inicio do bloco protegido contra erros inesperados.
    try:
        # Abre um cursor Firebird para executar consultas SQL.
        cursor = con.cursor()

        # Busca a folha desta empresa e le seu status.
        cursor.execute("SELECT STATUS FROM FOLHA_PAGAMENTO WHERE ID_FOLHA = ? AND ID_CONTA_EMPRESA = ?", (id_folha, id_conta))
        # fetchone() pega somente a primeira linha da consulta anterior.
        folha = cursor.fetchone()

        # Testa esta condicao antes de continuar.
        if not folha:
            # HTTP 404: registro nao encontrado.
            return jsonify({'mensagem': 'Folha nao encontrada'}), 404

        # STATUS 2 = folha em processamento.
        if folha[0] == 2:
            # HTTP 409: conflito, duplicidade ou estado que impede a operacao.
            return jsonify({'mensagem': 'Folha esta sendo processada'}), 409

        # Procura pelo CPF uma conta PF Arkhe que possa receber o salario.
        cursor.execute("SELECT ID_FOLHA_ITEM, ID_FUNCIONARIO, CPF FROM FOLHA_ITEM WHERE ID_FOLHA = ? AND STATUS = 0 AND ID_MOVIMENTACAO IS NULL", (id_folha,))
        # fetchall() pega todas as linhas retornadas.
        itens = cursor.fetchall()

        # Contador de pendencias resolvidas nesta tentativa.
        revalidados = 0

        # Processa cada item selecionado.
        for item in itens:
            # ID do FOLHA_ITEM atual.
            id_item = item[0]
            # ID do funcionario ligado ao item.
            id_funcionario = item[1]
            # CPF usado para procurar a conta PF.
            cpf = item[2]

            # Procura pelo CPF uma conta PF Arkhe que possa receber o salario.
            cursor.execute("""SELECT U.ID_USUARIO, C.ID_CONTA FROM USUARIO U INNER JOIN CONTA C ON C.ID_USUARIO = U.ID_USUARIO WHERE U.CPF = ? AND C.TIPO_CONTA = 0 ORDER BY C.ID_CONTA ROWS 1""", (cpf,))
            # fetchone() pega somente a primeira linha da consulta anterior.
            conta = cursor.fetchone()

            # Se encontrou conta, a pendencia pode ser resolvida.
            if conta:
                # ID_USUARIO encontrado.
                id_usuario = conta[0]
                # ID_CONTA PF que recebera o salario.
                id_conta_destino = conta[1]

                # Atualiza dados do funcionario.
                cursor.execute("UPDATE FOLHA_ITEM SET ID_CONTA_DESTINO = ?, STATUS = 1, ERRO = NULL WHERE ID_FOLHA_ITEM = ?", (id_conta_destino, id_item))
                # Atualiza dados do funcionario.
                cursor.execute("UPDATE FUNCIONARIO SET ID_USUARIO = ? WHERE ID_FUNCIONARIO = ? AND ID_CONTA_EMPRESA = ?", (id_usuario, id_funcionario, id_conta))

                # Incrementa o contador correspondente.
                revalidados += 1

        # Busca itens pendentes para tentar revalidar.
        cursor.execute("SELECT COUNT(*) FROM FOLHA_ITEM WHERE ID_FOLHA = ? AND STATUS = 0", (id_folha,))
        # Quantidade de itens que continuam pendentes.
        pendentes = cursor.fetchone()[0]

        # Sem pendencias: folha pode ficar pronta.
        if pendentes == 0 and folha[0] in (0, 1):
            # Atualiza dados/status da folha.
            cursor.execute("UPDATE FOLHA_PAGAMENTO SET STATUS = 1 WHERE ID_FOLHA = ?", (id_folha,))

        # COMMIT confirma definitivamente as alteracoes no Firebird.
        con.commit()

        # Monta a resposta JSON que sera enviada ao front.
        return jsonify({
            'mensagem': 'Folha revalidada com sucesso',
            'id_folha': id_folha,
            'revalidados': revalidados,
            'pendentes': pendentes
        }), 200

    # Captura erro inesperado para responder sem derrubar a API.
    except Exception as e:
        # ROLLBACK desfaz alteracoes ainda nao confirmadas.
        con.rollback()
        # HTTP 500: erro inesperado no servidor.
        return jsonify({'mensagem': 'Erro ao revalidar folha', 'erro': str(e)}), 500

    # Roda sempre, com sucesso ou erro.
    finally:
        # So fecha se o cursor realmente foi criado.
        if cursor:
            # Fecha o cursor para liberar o recurso.
            cursor.close()


# Registra no Flask a rota POST /pagar_folha.
# Quando o front chama esse endereco, a funcao logo abaixo e executada.
@app.route('/pagar_folha', methods=['POST'])
# ================================================================
# POST /pagar_folha
# Faz os pagamentos reais criando MOVIMENTACAO para cada item valido.
# Fluxo: trava folha -> confere saldo -> transfere -> marca itens pagos -> finaliza.
# STATUS FOLHA: 2=processando, 3=paga, 4=parcial.
# STATUS ITEM: 0=pendente, 1=pronto, 2=pago.
# ================================================================
def pagar_folha():
    # Valida login, acesso e se a conta atual e PJ.
    id_conta, erro = contexto_folha_pj()

    # Se a validacao encontrou problema, nao continua.
    if erro:
        # Devolve ao front o erro produzido pela validacao.
        return erro

    # Le o JSON enviado pelo front.
    dados = request.get_json()
    # Le do JSON qual folha sera manipulada.
    id_folha = dados.get('id_folha')

    # Sem ID_FOLHA nao ha como revalidar ou pagar.
    if not id_folha:
        # HTTP 400: dados enviados sao invalidos/incompletos.
        return jsonify({'mensagem': 'Folha nao informada'}), 400

    # Comeca sem cursor para o finally saber se precisa fecha-lo.
    cursor = None

    # Inicio do bloco protegido contra erros inesperados.
    try:
        # Abre um cursor Firebird para executar consultas SQL.
        cursor = con.cursor()

        # Busca a folha desta empresa e le seu status.
        cursor.execute("SELECT STATUS FROM FOLHA_PAGAMENTO WHERE ID_FOLHA = ? AND ID_CONTA_EMPRESA = ?", (id_folha, id_conta))
        # fetchone() pega somente a primeira linha da consulta anterior.
        folha = cursor.fetchone()

        # Testa esta condicao antes de continuar.
        if not folha:
            # HTTP 404: registro nao encontrado.
            return jsonify({'mensagem': 'Folha nao encontrada'}), 404

        # STATUS 3 = folha ja totalmente paga.
        if folha[0] == 3:
            # HTTP 400: dados enviados sao invalidos/incompletos.
            return jsonify({'mensagem': 'Esta folha ja foi paga'}), 400

        # STATUS 2 = folha em processamento.
        if folha[0] == 2:
            # HTTP 409: conflito, duplicidade ou estado que impede a operacao.
            return jsonify({'mensagem': 'Esta folha esta sendo processada'}), 409

        # Busca itens prontos para pagamento e ainda sem movimentacao.
        cursor.execute("UPDATE FOLHA_PAGAMENTO SET STATUS = 2 WHERE ID_FOLHA = ? AND ID_CONTA_EMPRESA = ? AND STATUS IN (0,1,4) RETURNING ID_FOLHA", (id_folha, id_conta))
        # fetchone() pega somente a primeira linha da consulta anterior.
        bloqueio = cursor.fetchone()

        # Se nao travou, outra execucao ja processou ou esta processando.
        if not bloqueio:
            # ROLLBACK desfaz alteracoes ainda nao confirmadas.
            con.rollback()
            # HTTP 409: conflito, duplicidade ou estado que impede a operacao.
            return jsonify({'mensagem': 'Folha ja paga ou em processamento'}), 409

        # Busca itens prontos para pagamento e ainda sem movimentacao.
        cursor.execute("SELECT ID_FOLHA_ITEM, ID_CONTA_DESTINO, VALOR FROM FOLHA_ITEM WHERE ID_FOLHA = ? AND STATUS = 1 AND ID_MOVIMENTACAO IS NULL", (id_folha,))
        # fetchall() pega todas as linhas retornadas.
        itens = cursor.fetchall()

        # Testa esta condicao antes de continuar.
        if not itens:
            # ROLLBACK desfaz alteracoes ainda nao confirmadas.
            con.rollback()
            # HTTP 400: dados enviados sao invalidos/incompletos.
            return jsonify({'mensagem': 'Nenhum pagamento disponivel nesta folha'}), 400

        # Soma somente os itens que serao pagos agora.
        total = sum(float(item[2]) for item in itens)
        # Calcula o saldo atual da empresa.
        saldo = calcular_saldo(id_conta)

        # Verifica se a empresa pode debitar o total antes das transferencias.
        if not pode_debitar_saldo(id_conta, total):
            # ROLLBACK desfaz alteracoes ainda nao confirmadas.
            con.rollback()

            # Monta a resposta JSON que sera enviada ao front.
            return jsonify({
                'mensagem': 'Saldo insuficiente para pagar a folha',
                'saldo': float(saldo),
                'total_folha': total
            }), 400

        # Lista das movimentacoes criadas nesta execucao.
        pagamentos = []

        # Processa cada item selecionado.
        for item in itens:
            # ID do FOLHA_ITEM atual.
            id_item = item[0]
            # Conta PF que recebera este salario.
            id_destino = item[1]
            # Valor do salario deste item.
            valor = item[2]
            # Data/hora usada no registro financeiro.
            data_movimentacao = data_atual()

            # Busca itens prontos para pagamento e ainda sem movimentacao.
            cursor.execute("INSERT INTO MOVIMENTACAO (ID_PAGADOR, ID_RECEBEDOR, VALOR, DATA_MOVIMENTACAO) VALUES (?, ?, ?, ?) RETURNING ID_MOVIMENTACAO", (id_conta, id_destino, valor, data_movimentacao))
            # ID da transferencia criada.
            id_movimentacao = cursor.fetchone()[0]

            # Busca itens prontos para pagamento e ainda sem movimentacao.
            cursor.execute("UPDATE FOLHA_ITEM SET STATUS = 2, ID_MOVIMENTACAO = ?, DATA_PAGAMENTO = ? WHERE ID_FOLHA_ITEM = ? AND STATUS = 1 AND ID_MOVIMENTACAO IS NULL", (id_movimentacao, data_movimentacao, id_item))

            # Guarda no retorno os dados do pagamento realizado.
            pagamentos.append({
                'id_item': id_item,
                'id_movimentacao': id_movimentacao,
                'valor': float(valor)
            })

        # Busca os itens que pertencem a esta folha.
        cursor.execute("SELECT COUNT(*) FROM FOLHA_ITEM WHERE ID_FOLHA = ? AND STATUS <> 2", (id_folha,))
        # Quantidade de itens que continuam pendentes.
        pendentes = cursor.fetchone()[0]

        # 3 se tudo foi pago; 4 se restou alguma pendencia.
        status_folha = 3 if pendentes == 0 else 4

        # Atualiza dados/status da folha.
        cursor.execute("UPDATE FOLHA_PAGAMENTO SET STATUS = ?, DATA_PAGAMENTO = CURRENT_TIMESTAMP WHERE ID_FOLHA = ?", (status_folha, id_folha))

        # COMMIT confirma definitivamente as alteracoes no Firebird.
        con.commit()

        # Monta a resposta JSON que sera enviada ao front.
        return jsonify({
            'mensagem': 'Folha processada com sucesso',
            'id_folha': id_folha,
            'total_pago': total,
            'quantidade_pagamentos': len(pagamentos),
            'status': status_folha,
            'pagamentos': pagamentos
        }), 200

    # Captura erro inesperado para responder sem derrubar a API.
    except Exception as e:
        # ROLLBACK desfaz alteracoes ainda nao confirmadas.
        con.rollback()
        # HTTP 500: erro inesperado no servidor.
        return jsonify({'mensagem': 'Erro ao pagar folha', 'erro': str(e)}), 500

    # Roda sempre, com sucesso ou erro.
    finally:
        # So fecha se o cursor realmente foi criado.
        if cursor:
            # Fecha o cursor para liberar o recurso.
            cursor.close()
