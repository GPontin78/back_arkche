import datetime
import os
import secrets
from calendar import monthrange
from zoneinfo import ZoneInfo

import jwt
from flask import jsonify, request

from banco import con
from funcao import calcular_limite_cartao, calcular_saldo, usuario_pode_acessar_conta
from main import app


CARGOS = {
    0: 'Administrativo',
    1: 'Financeiro',
    2: 'Contador',
    3: 'RH',
    4: 'Compras',
    5: 'Outro'
}


def autenticar_requisicao_mcp():
    """Valida o serviço MCP e a sessão bancária emitida pelo backend."""
    chave_esperada = os.getenv('MCP_SERVICE_KEY')
    chave_recebida = request.headers.get('X-Arkhe-MCP-Key')
    token_sessao = request.headers.get('X-Arkhe-Session')

    if not chave_esperada:
        return None, (jsonify({'mensagem': 'Integração MCP não configurada'}), 503)

    if not chave_recebida or not secrets.compare_digest(chave_recebida, chave_esperada):
        return None, (jsonify({'mensagem': 'Serviço MCP não autorizado'}), 401)

    if not token_sessao:
        return None, (jsonify({'mensagem': 'Sessão Arkhé não informada'}), 401)

    try:
        payload = jwt.decode(
            token_sessao,
            app.config['SECRET_KEY'],
            algorithms=['HS256']
        )
    except jwt.ExpiredSignatureError:
        return None, (jsonify({'mensagem': 'Sessão Arkhé expirada'}), 401)
    except Exception:
        return None, (jsonify({'mensagem': 'Sessão Arkhé inválida'}), 401)

    if payload.get('escopo') != 'mcp':
        return None, (jsonify({'mensagem': 'Sessão Arkhé inválida'}), 401)

    try:
        id_usuario = int(payload['id_usuario'])
        id_conta = int(payload['id_conta'])
    except (KeyError, TypeError, ValueError):
        return None, (jsonify({'mensagem': 'Sessão Arkhé inválida'}), 401)

    if not usuario_pode_acessar_conta(id_usuario, id_conta):
        return None, (jsonify({'mensagem': 'Usuário sem acesso à conta selecionada'}), 403)

    return {
        'id_usuario': id_usuario,
        'id_conta': id_conta,
        'canal': payload.get('canal')
    }, None


def buscar_dados_conta_mcp(id_usuario, id_conta):
    cursor = None

    try:
        cursor = con.cursor()
        cursor.execute(
            """SELECT C.ID_CONTA, C.ID_USUARIO, C.NUMERO_CONTA, C.AGENCIA,
                      C.BANCO, C.TIPO_CONTA, C.NOME_FANTASIA, C.RAZAO_SOCIAL,
                      U.NOME
               FROM CONTA C
               INNER JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
               WHERE C.ID_CONTA = ?""",
            (id_conta,)
        )
        conta = cursor.fetchone()

        if not conta:
            return None

        id_titular = conta[1]
        tipo_conta = conta[5]
        cargo = None
        cargo_nome = None

        if id_titular == id_usuario:
            vinculo = 'titular' if tipo_conta == 0 else 'proprietario'
        else:
            vinculo = 'acesso'
            cursor.execute(
                """SELECT CARGO
                   FROM ACESSO_CONTA
                   WHERE ID_CONTA = ? AND ID_USUARIO = ? AND STATUS = 1""",
                (id_conta, id_usuario)
            )
            acesso = cursor.fetchone()

            if not acesso:
                return None

            cargo = acesso[0]
            cargo_nome = CARGOS.get(cargo, 'Outro')

        nome = conta[8]

        if tipo_conta == 1:
            nome = conta[6] or conta[7] or conta[8] or 'Empresa Arkhé'

        return {
            'id_conta': conta[0],
            'numero_conta': conta[2],
            'agencia': conta[3],
            'banco': conta[4],
            'tipo_conta': tipo_conta,
            'nome': nome,
            'vinculo': vinculo,
            'cargo': cargo,
            'cargo_nome': cargo_nome
        }

    finally:
        if cursor:
            cursor.close()


@app.route('/internal/mcp/conta', methods=['GET'])
def mcp_consultar_conta():
    contexto, erro = autenticar_requisicao_mcp()

    if erro:
        return erro

    try:
        conta = buscar_dados_conta_mcp(
            contexto['id_usuario'],
            contexto['id_conta']
        )

        if not conta:
            return jsonify({'mensagem': 'Conta não encontrada'}), 404

        return jsonify(conta), 200

    except Exception as e:
        print('ERRO MCP CONSULTAR CONTA:', e)
        return jsonify({'mensagem': 'Erro ao consultar conta'}), 500


@app.route('/internal/mcp/saldo', methods=['GET'])
def mcp_consultar_saldo():
    contexto, erro = autenticar_requisicao_mcp()

    if erro:
        return erro

    try:
        saldo = calcular_saldo(contexto['id_conta'])

        if saldo is None:
            return jsonify({'mensagem': 'Conta não encontrada'}), 404

        return jsonify({
            'saldo': float(saldo)
        }), 200

    except Exception as e:
        print('ERRO MCP CONSULTAR SALDO:', e)
        return jsonify({'mensagem': 'Erro ao consultar saldo'}), 500



def nome_cliente_mcp(nome, nome_fantasia, razao_social, tipo_conta):
    if tipo_conta == 1:
        return nome_fantasia or razao_social or nome or 'Conta Arkhé'

    return nome or 'Conta Arkhé'


def limitar_resultados(valor, padrao=50, maximo=200):
    try:
        valor = int(valor)
    except (TypeError, ValueError):
        valor = padrao

    return max(1, min(valor, maximo))


def situacao_cobranca_mcp(status, vencimento):
    status = int(status or 0)

    if status == 1:
        return 'PAGO'

    hoje = datetime.datetime.now(ZoneInfo('America/Sao_Paulo')).date()

    if vencimento and vencimento < hoje:
        return 'VENCIDO'

    return 'PENDENTE'


def obter_periodo_extrato_mcp():
    data_inicio = request.args.get('data_inicio')
    data_fim = request.args.get('data_fim')
    hoje = datetime.date.today()

    if not data_inicio and not data_fim:
        return hoje.replace(day=1), hoje, None

    if not data_inicio or not data_fim:
        return None, None, (jsonify({
            'mensagem': 'Informe data_inicio e data_fim juntas'
        }), 400)

    try:
        inicio = datetime.date.fromisoformat(data_inicio)
        fim = datetime.date.fromisoformat(data_fim)
    except ValueError:
        return None, None, (jsonify({
            'mensagem': 'Datas inválidas. Use YYYY-MM-DD'
        }), 400)

    if inicio > fim:
        return None, None, (jsonify({
            'mensagem': 'data_inicio não pode ser maior que data_fim'
        }), 400)

    return inicio, fim, None


def data_fechamento_parcela_mcp(data_parcela, dia_fechamento):
    dia = min(int(dia_fechamento), monthrange(data_parcela.year, data_parcela.month)[1])
    fechamento = datetime.date(data_parcela.year, data_parcela.month, dia)

    if data_parcela <= fechamento:
        return fechamento

    mes = data_parcela.month + 1
    ano = data_parcela.year

    if mes == 13:
        mes = 1
        ano += 1

    dia = min(int(dia_fechamento), monthrange(ano, mes)[1])
    return datetime.date(ano, mes, dia)


def data_vencimento_fatura_mcp(data_fechamento, dia_vencimento):
    dia = min(
        int(dia_vencimento),
        monthrange(data_fechamento.year, data_fechamento.month)[1]
    )
    return datetime.date(data_fechamento.year, data_fechamento.month, dia)


@app.route('/internal/mcp/extrato', methods=['GET'])
def mcp_consultar_extrato():
    contexto, erro = autenticar_requisicao_mcp()

    if erro:
        return erro

    inicio, fim, erro_periodo = obter_periodo_extrato_mcp()

    if erro_periodo:
        return erro_periodo

    limite = limitar_resultados(request.args.get('limite'))
    id_conta = contexto['id_conta']
    cursor = None

    try:
        cursor = con.cursor()
        cursor.execute(
            """SELECT M.ID_MOVIMENTACAO, M.ID_PAGADOR, M.ID_RECEBEDOR,
                      M.VALOR, M.DATA_MOVIMENTACAO, M.ID_COBRANCA,
                      COB.TIPO_COBRANCA,
                      UP.NOME, CP.NOME_FANTASIA, CP.RAZAO_SOCIAL, CP.TIPO_CONTA,
                      UR.NOME, CR.NOME_FANTASIA, CR.RAZAO_SOCIAL, CR.TIPO_CONTA,
                      FI.ID_FOLHA,
                      CASE WHEN EXISTS (
                          SELECT 1
                          FROM COMPRA CMP
                          INNER JOIN CARTAO CAT ON CAT.ID_CARTAO = CMP.ID_CARTAO
                          WHERE CAT.ID_CONTA = M.ID_PAGADOR
                            AND CMP.VALOR_COMPRA = M.VALOR
                            AND CMP.DATA_COMPRA = M.DATA_MOVIMENTACAO
                            AND CMP.TIPO = 0
                      ) THEN 1 ELSE 0 END AS COMPRA_CARTAO
               FROM MOVIMENTACAO M
               INNER JOIN CONTA CP ON CP.ID_CONTA = M.ID_PAGADOR
               INNER JOIN USUARIO UP ON UP.ID_USUARIO = CP.ID_USUARIO
               INNER JOIN CONTA CR ON CR.ID_CONTA = M.ID_RECEBEDOR
               INNER JOIN USUARIO UR ON UR.ID_USUARIO = CR.ID_USUARIO
               LEFT JOIN COBRANCA COB ON COB.ID_COBRANCA = M.ID_COBRANCA
               LEFT JOIN FOLHA_ITEM FI ON FI.ID_MOVIMENTACAO = M.ID_MOVIMENTACAO
               WHERE (M.ID_PAGADOR = ? OR M.ID_RECEBEDOR = ?)
                 AND M.DATA_MOVIMENTACAO >= CAST(? AS DATE)
                 AND M.DATA_MOVIMENTACAO < DATEADD(1 DAY TO CAST(? AS DATE))
               ORDER BY M.DATA_MOVIMENTACAO DESC""",
            (id_conta, id_conta, inicio.isoformat(), fim.isoformat())
        )

        movimentacoes = []

        for movimentacao in cursor.fetchall()[:limite]:
            tipo = 'saida' if movimentacao[1] == id_conta else 'entrada'

            if movimentacao[15] is not None:
                origem = 'folha_pagamento'
            elif movimentacao[16] == 1:
                origem = 'compra_cartao'
            elif movimentacao[5] is None:
                origem = 'pix'
            elif movimentacao[6] == 1:
                origem = 'pix_qrcode'
            else:
                origem = 'boleto'

            nome_pagador = nome_cliente_mcp(
                movimentacao[7], movimentacao[8],
                movimentacao[9], movimentacao[10]
            )
            nome_recebedor = nome_cliente_mcp(
                movimentacao[11], movimentacao[12],
                movimentacao[13], movimentacao[14]
            )

            movimentacoes.append({
                'id_movimentacao': movimentacao[0],
                'valor': float(movimentacao[3]),
                'data_movimentacao': str(movimentacao[4]),
                'tipo': tipo,
                'origem': origem,
                'nome_pagador': nome_pagador,
                'nome_recebedor': nome_recebedor,
                'nome_contraparte': nome_recebedor if tipo == 'saida' else nome_pagador,
                'id_cobranca': movimentacao[5],
                'id_folha': movimentacao[15]
            })

        return jsonify({
            'data_inicio': inicio.isoformat(),
            'data_fim': fim.isoformat(),
            'movimentacoes': movimentacoes
        }), 200

    except Exception as e:
        print('ERRO MCP CONSULTAR EXTRATO:', e)
        return jsonify({'mensagem': 'Erro ao consultar extrato'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/internal/mcp/dda', methods=['GET'])
def mcp_consultar_dda():
    contexto, erro = autenticar_requisicao_mcp()

    if erro:
        return erro

    limite = limitar_resultados(request.args.get('limite'))
    id_conta = contexto['id_conta']
    cursor = None

    try:
        cursor = con.cursor()
        cursor.execute(
            """SELECT COB.ID_COBRANCA, COB.VALOR, COB.DATA_VENCIMENTO,
                      COB.STATUS, COB.CODIGO_PAGAMENTO,
                      U.NOME, C.NOME_FANTASIA, C.RAZAO_SOCIAL, C.TIPO_CONTA
               FROM COBRANCA COB
               INNER JOIN CONTA C ON C.ID_CONTA = COB.ID_RECEBEDOR
               INNER JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
               WHERE COB.ID_PAGADOR = ? AND COB.TIPO_COBRANCA = 0
               ORDER BY COB.STATUS, COB.DATA_VENCIMENTO, COB.ID_COBRANCA DESC""",
            (id_conta,)
        )

        boletos = []

        for cobranca in cursor.fetchall()[:limite]:
            boletos.append({
                'id_cobranca': cobranca[0],
                'valor': float(cobranca[1] or 0),
                'data_vencimento': str(cobranca[2]) if cobranca[2] else None,
                'status': int(cobranca[3] or 0),
                'situacao': situacao_cobranca_mcp(cobranca[3], cobranca[2]),
                'codigo_pagamento': cobranca[4],
                'recebedor': nome_cliente_mcp(
                    cobranca[5], cobranca[6], cobranca[7], cobranca[8]
                )
            })

        cursor.execute(
            """SELECT COUNT(*)
               FROM COBRANCA
               WHERE ID_PAGADOR = ? AND TIPO_COBRANCA = 0 AND STATUS = 0""",
            (id_conta,)
        )
        total_pendentes = int(cursor.fetchone()[0] or 0)

        return jsonify({
            'dda': boletos,
            'total_pendentes': total_pendentes
        }), 200

    except Exception as e:
        print('ERRO MCP CONSULTAR DDA:', e)
        return jsonify({'mensagem': 'Erro ao consultar DDA'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/internal/mcp/boletos', methods=['GET'])
def mcp_consultar_boletos():
    contexto, erro = autenticar_requisicao_mcp()

    if erro:
        return erro

    limite = limitar_resultados(request.args.get('limite'))
    id_conta = contexto['id_conta']
    cursor = None

    try:
        cursor = con.cursor()
        cursor.execute(
            """SELECT COB.ID_COBRANCA, COB.ID_PAGADOR, COB.ID_RECEBEDOR,
                      COB.VALOR, COB.DATA_VENCIMENTO, COB.STATUS,
                      COB.CODIGO_PAGAMENTO,
                      UP.NOME, CP.NOME_FANTASIA, CP.RAZAO_SOCIAL, CP.TIPO_CONTA,
                      UR.NOME, CR.NOME_FANTASIA, CR.RAZAO_SOCIAL, CR.TIPO_CONTA
               FROM COBRANCA COB
               INNER JOIN CONTA CP ON CP.ID_CONTA = COB.ID_PAGADOR
               INNER JOIN USUARIO UP ON UP.ID_USUARIO = CP.ID_USUARIO
               INNER JOIN CONTA CR ON CR.ID_CONTA = COB.ID_RECEBEDOR
               INNER JOIN USUARIO UR ON UR.ID_USUARIO = CR.ID_USUARIO
               WHERE (COB.ID_PAGADOR = ? OR COB.ID_RECEBEDOR = ?)
                 AND COB.TIPO_COBRANCA = 0
               ORDER BY COB.DATA_VENCIMENTO DESC, COB.ID_COBRANCA DESC""",
            (id_conta, id_conta)
        )

        boletos = []

        for cobranca in cursor.fetchall()[:limite]:
            tipo = 'pagar' if cobranca[1] == id_conta else 'receber'
            nome_pagador = nome_cliente_mcp(
                cobranca[7], cobranca[8], cobranca[9], cobranca[10]
            )
            nome_recebedor = nome_cliente_mcp(
                cobranca[11], cobranca[12], cobranca[13], cobranca[14]
            )

            boletos.append({
                'id_cobranca': cobranca[0],
                'tipo': tipo,
                'valor': float(cobranca[3] or 0),
                'data_vencimento': str(cobranca[4]) if cobranca[4] else None,
                'status': int(cobranca[5] or 0),
                'situacao': situacao_cobranca_mcp(cobranca[5], cobranca[4]),
                'codigo_pagamento': cobranca[6],
                'pagador': nome_pagador,
                'recebedor': nome_recebedor
            })

        return jsonify({'boletos': boletos}), 200

    except Exception as e:
        print('ERRO MCP CONSULTAR BOLETOS:', e)
        return jsonify({'mensagem': 'Erro ao consultar boletos'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/internal/mcp/faturas', methods=['GET'])
def mcp_consultar_faturas():
    contexto, erro = autenticar_requisicao_mcp()

    if erro:
        return erro

    id_conta = contexto['id_conta']
    cursor = None

    try:
        cursor = con.cursor()
        cursor.execute(
            """SELECT ID_CARTAO, FECHAMENTO, DIA_VENCIMENTO
               FROM CARTAO
               WHERE ID_CONTA = ?""",
            (id_conta,)
        )
        cartao = cursor.fetchone()

        if not cartao:
            return jsonify({
                'possui_cartao': False,
                'faturas': [],
                'proximas_faturas': []
            }), 200

        id_cartao, dia_fechamento, dia_vencimento = cartao

        cursor.execute(
            """SELECT ID_FATURA, VALOR_TOTAL, STATUS,
                      DATA_FECHAMENTO, DATA_VENCIMENTO
               FROM FATURA
               WHERE ID_CONTA = ?
               ORDER BY DATA_FECHAMENTO DESC, ID_FATURA DESC""",
            (id_conta,)
        )

        hoje = datetime.datetime.now(ZoneInfo('America/Sao_Paulo')).date()
        faturas = []

        for fatura in cursor.fetchall():
            status = int(fatura[2] or 0)
            vencimento = fatura[4]

            if status == 1:
                situacao = 'PAGA'
            elif vencimento and vencimento < hoje:
                situacao = 'VENCIDA'
            else:
                situacao = 'FECHADA'

            faturas.append({
                'id_fatura': fatura[0],
                'valor_total': float(fatura[1] or 0),
                'status': status,
                'situacao': situacao,
                'data_fechamento': str(fatura[3]) if fatura[3] else None,
                'data_vencimento': str(vencimento) if vencimento else None
            })

        cursor.execute(
            """SELECT FC.VALOR_PARCELA, FC.DATA_PARCELA
               FROM FATURA_COMPRA FC
               INNER JOIN COMPRA C ON C.ID_COMPRA = FC.ID_COMPRA
               WHERE C.ID_CARTAO = ?
                 AND FC.ID_FATURA IS NULL
                 AND FC.STATUS = 0
               ORDER BY FC.DATA_PARCELA, FC.NUMERO_PARCELA""",
            (id_cartao,)
        )

        futuras = {}

        for parcela in cursor.fetchall():
            data_parcela = parcela[1]

            if not data_parcela:
                continue

            fechamento = data_fechamento_parcela_mcp(
                data_parcela,
                dia_fechamento
            )
            chave = str(fechamento)

            if chave not in futuras:
                futuras[chave] = {
                    'data_fechamento': chave,
                    'data_vencimento': str(
                        data_vencimento_fatura_mcp(
                            fechamento,
                            dia_vencimento
                        )
                    ),
                    'valor_total': 0.0,
                    'situacao': 'PREVISTA',
                    'parcelas': 0
                }

            futuras[chave]['valor_total'] += float(parcela[0] or 0)
            futuras[chave]['parcelas'] += 1

        proximas_faturas = list(futuras.values())

        for fatura in proximas_faturas:
            fatura['valor_total'] = round(fatura['valor_total'], 2)

        return jsonify({
            'possui_cartao': True,
            'faturas': faturas[:12],
            'proximas_faturas': proximas_faturas,
            'fatura_atual': faturas[0] if faturas else None,
            'proxima_fatura': proximas_faturas[0] if proximas_faturas else None
        }), 200

    except Exception as e:
        print('ERRO MCP CONSULTAR FATURAS:', e)
        return jsonify({'mensagem': 'Erro ao consultar faturas'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/internal/mcp/limites', methods=['GET'])
def mcp_consultar_limites():
    contexto, erro = autenticar_requisicao_mcp()

    if erro:
        return erro

    id_conta = contexto['id_conta']
    cursor = None

    try:
        cursor = con.cursor()
        cursor.execute(
            """SELECT ID_CARTAO, LIMITE, DIA_VENCIMENTO, FECHAMENTO, STATUS
               FROM CARTAO
               WHERE ID_CONTA = ?""",
            (id_conta,)
        )
        cartao = cursor.fetchone()

        if not cartao:
            return jsonify({
                'possui_cartao': False,
                'limites': None
            }), 200

        limite_total = float(cartao[1] or 0)
        limite_utilizado = float(calcular_limite_cartao(cartao[0]) or 0)

        return jsonify({
            'possui_cartao': True,
            'limites': {
                'limite_total': limite_total,
                'limite_utilizado': limite_utilizado,
                'limite_disponivel': round(limite_total - limite_utilizado, 2),
                'dia_vencimento': cartao[2],
                'dia_fechamento': cartao[3],
                'cartao_bloqueado': int(cartao[4] or 0) == 1
            }
        }), 200

    except Exception as e:
        print('ERRO MCP CONSULTAR LIMITES:', e)
        return jsonify({'mensagem': 'Erro ao consultar limites'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/internal/mcp/chaves-pix', methods=['GET'])
def mcp_listar_chaves_pix():
    contexto, erro = autenticar_requisicao_mcp()

    if erro:
        return erro

    id_conta = contexto['id_conta']
    cursor = None

    try:
        cursor = con.cursor()
        cursor.execute(
            """SELECT ID_CHAVE_PIX, CHAVE_PIX_EMAIL, CHAVE_PIX_TELEFONE,
                      CHAVE_PIX_CPF, CHAVE_PIX_ALEATORIA, CHAVE_PIX_CNPJ
               FROM CHAVE_PIX
               WHERE ID_CONTA = ?""",
            (id_conta,)
        )

        chaves = []

        for registro in cursor.fetchall():
            for tipo, valor in (
                ('email', registro[1]),
                ('telefone', registro[2]),
                ('cpf', registro[3]),
                ('aleatoria', registro[4]),
                ('cnpj', registro[5]),
            ):
                if valor:
                    chaves.append({
                        'id_chave_pix': registro[0],
                        'tipo': tipo,
                        'valor': valor
                    })

        return jsonify({'chaves': chaves}), 200

    except Exception as e:
        print('ERRO MCP LISTAR CHAVES PIX:', e)
        return jsonify({'mensagem': 'Erro ao consultar chaves Pix'}), 500

    finally:
        if cursor:
            cursor.close()



STATUS_FOLHA_MCP = {
    0: 'PENDENTE',
    1: 'PRONTA',
    2: 'PROCESSANDO',
    3: 'PAGA',
    4: 'PARCIAL'
}

STATUS_ITEM_FOLHA_MCP = {
    0: 'PENDENTE',
    1: 'PRONTO',
    2: 'PAGO'
}


def mascarar_cpf_mcp(valor):
    cpf = ''.join(numero for numero in str(valor or '') if numero.isdigit())

    if len(cpf) != 11:
        return None

    return '***.***.***-' + cpf[-2:]


def autorizar_rh_mcp(contexto):
    """Restringe dados de funcionários e folha ao proprietário ou RH ativo."""
    cursor = None

    try:
        cursor = con.cursor()
        cursor.execute(
            """SELECT ID_USUARIO, TIPO_CONTA
               FROM CONTA
               WHERE ID_CONTA = ?""",
            (contexto['id_conta'],)
        )
        conta = cursor.fetchone()

        if not conta:
            return None, (jsonify({'mensagem': 'Conta não encontrada'}), 404)

        if conta[1] != 1:
            return None, (jsonify({
                'mensagem': 'Funcionários e folha estão disponíveis apenas para conta PJ'
            }), 403)

        if conta[0] == contexto['id_usuario']:
            return {
                'vinculo': 'proprietario',
                'cargo': None,
                'cargo_nome': 'Proprietário'
            }, None

        cursor.execute(
            """SELECT CARGO
               FROM ACESSO_CONTA
               WHERE ID_CONTA = ? AND ID_USUARIO = ? AND STATUS = 1""",
            (contexto['id_conta'], contexto['id_usuario'])
        )
        acesso = cursor.fetchone()

        if not acesso:
            return None, (jsonify({
                'mensagem': 'Usuário sem acesso ativo à empresa'
            }), 403)

        cargo = int(acesso[0])

        if cargo != 3:
            return None, (jsonify({
                'mensagem': 'Seu cargo não permite consultar funcionários ou folha'
            }), 403)

        return {
            'vinculo': 'acesso',
            'cargo': cargo,
            'cargo_nome': CARGOS.get(cargo, 'Outro')
        }, None

    finally:
        if cursor:
            cursor.close()


@app.route('/internal/mcp/funcionarios', methods=['GET'])
def mcp_listar_funcionarios():
    contexto, erro = autenticar_requisicao_mcp()

    if erro:
        return erro

    _permissao, erro = autorizar_rh_mcp(contexto)

    if erro:
        return erro

    id_conta = contexto['id_conta']
    cursor = None

    try:
        cursor = con.cursor()
        cursor.execute(
            """SELECT F.ID_FUNCIONARIO, F.CPF, F.NOME, F.SALARIO,
                      F.STATUS, F.DATA_CADASTRO,
                      CASE WHEN EXISTS (
                          SELECT 1
                          FROM CONTA C
                          WHERE C.ID_USUARIO = F.ID_USUARIO
                            AND C.TIPO_CONTA = 0
                      ) THEN 1 ELSE 0 END AS POSSUI_CONTA_PF
               FROM FUNCIONARIO F
               WHERE F.ID_CONTA_EMPRESA = ?
               ORDER BY F.STATUS DESC, F.NOME""",
            (id_conta,)
        )

        funcionarios = []
        total_ativos = 0
        total_inativos = 0
        folha_mensal_ativa = 0.0

        for funcionario in cursor.fetchall():
            status = int(funcionario[4] or 0)
            salario = float(funcionario[3] or 0)

            if status == 1:
                total_ativos += 1
                folha_mensal_ativa += salario
            else:
                total_inativos += 1

            funcionarios.append({
                'id_funcionario': funcionario[0],
                'nome': funcionario[2],
                'cpf_mascarado': mascarar_cpf_mcp(funcionario[1]),
                'salario': salario,
                'status': status,
                'status_nome': 'ATIVO' if status == 1 else 'INATIVO',
                'data_cadastro': str(funcionario[5]) if funcionario[5] else None,
                'possui_conta_arkhe': bool(funcionario[6])
            })

        return jsonify({
            'resumo': {
                'total_funcionarios': len(funcionarios),
                'ativos': total_ativos,
                'inativos': total_inativos,
                'folha_mensal_ativa': round(folha_mensal_ativa, 2)
            },
            'funcionarios': funcionarios
        }), 200

    except Exception as e:
        print('ERRO MCP LISTAR FUNCIONARIOS:', e)
        return jsonify({'mensagem': 'Erro ao consultar funcionários'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/internal/mcp/funcionarios/<int:id_funcionario>', methods=['GET'])
def mcp_consultar_funcionario(id_funcionario):
    contexto, erro = autenticar_requisicao_mcp()

    if erro:
        return erro

    _permissao, erro = autorizar_rh_mcp(contexto)

    if erro:
        return erro

    cursor = None

    try:
        cursor = con.cursor()
        cursor.execute(
            """SELECT F.ID_FUNCIONARIO, F.CPF, F.NOME, F.SALARIO,
                      F.STATUS, F.DATA_CADASTRO,
                      CASE WHEN EXISTS (
                          SELECT 1
                          FROM CONTA C
                          WHERE C.ID_USUARIO = F.ID_USUARIO
                            AND C.TIPO_CONTA = 0
                      ) THEN 1 ELSE 0 END AS POSSUI_CONTA_PF
               FROM FUNCIONARIO F
               WHERE F.ID_FUNCIONARIO = ?
                 AND F.ID_CONTA_EMPRESA = ?""",
            (id_funcionario, contexto['id_conta'])
        )
        funcionario = cursor.fetchone()

        if not funcionario:
            return jsonify({'mensagem': 'Funcionário não encontrado'}), 404

        status = int(funcionario[4] or 0)

        return jsonify({
            'id_funcionario': funcionario[0],
            'nome': funcionario[2],
            'cpf_mascarado': mascarar_cpf_mcp(funcionario[1]),
            'salario': float(funcionario[3] or 0),
            'status': status,
            'status_nome': 'ATIVO' if status == 1 else 'INATIVO',
            'data_cadastro': str(funcionario[5]) if funcionario[5] else None,
            'possui_conta_arkhe': bool(funcionario[6])
        }), 200

    except Exception as e:
        print('ERRO MCP CONSULTAR FUNCIONARIO:', e)
        return jsonify({'mensagem': 'Erro ao consultar funcionário'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/internal/mcp/folhas', methods=['GET'])
def mcp_listar_folhas():
    contexto, erro = autenticar_requisicao_mcp()

    if erro:
        return erro

    _permissao, erro = autorizar_rh_mcp(contexto)

    if erro:
        return erro

    limite = limitar_resultados(request.args.get('limite'), padrao=12, maximo=60)
    cursor = None

    try:
        cursor = con.cursor()
        cursor.execute(
            """SELECT FP.ID_FOLHA, FP.COMPETENCIA_MES, FP.COMPETENCIA_ANO,
                      FP.STATUS, FP.DATA_CRIACAO, FP.DATA_PAGAMENTO,
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
               GROUP BY FP.ID_FOLHA, FP.COMPETENCIA_MES, FP.COMPETENCIA_ANO,
                        FP.STATUS, FP.DATA_CRIACAO, FP.DATA_PAGAMENTO
               ORDER BY FP.COMPETENCIA_ANO DESC,
                        FP.COMPETENCIA_MES DESC,
                        FP.ID_FOLHA DESC""",
            (contexto['id_conta'],)
        )

        folhas = []

        for folha in cursor.fetchall()[:limite]:
            status = int(folha[3] or 0)

            folhas.append({
                'id_folha': folha[0],
                'mes': folha[1],
                'ano': folha[2],
                'status': status,
                'status_nome': STATUS_FOLHA_MCP.get(status, 'DESCONHECIDO'),
                'data_criacao': str(folha[4]) if folha[4] else None,
                'data_pagamento': str(folha[5]) if folha[5] else None,
                'total': float(folha[6] or 0),
                'total_pago': float(folha[7] or 0),
                'total_valido': float(folha[8] or 0),
                'total_pendente': float(folha[9] or 0),
                'quantidade_funcionarios': int(folha[10] or 0),
                'quantidade_pagos': int(folha[11] or 0),
                'quantidade_validos': int(folha[12] or 0),
                'quantidade_pendentes': int(folha[13] or 0)
            })

        return jsonify({
            'folhas': folhas,
            'quantidade_retornada': len(folhas)
        }), 200

    except Exception as e:
        print('ERRO MCP LISTAR FOLHAS:', e)
        return jsonify({'mensagem': 'Erro ao consultar folhas'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/internal/mcp/folhas/<int:id_folha>', methods=['GET'])
def mcp_consultar_folha(id_folha):
    contexto, erro = autenticar_requisicao_mcp()

    if erro:
        return erro

    _permissao, erro = autorizar_rh_mcp(contexto)

    if erro:
        return erro

    cursor = None

    try:
        cursor = con.cursor()
        cursor.execute(
            """SELECT ID_FOLHA, COMPETENCIA_MES, COMPETENCIA_ANO,
                      STATUS, DATA_CRIACAO, DATA_PAGAMENTO
               FROM FOLHA_PAGAMENTO
               WHERE ID_FOLHA = ? AND ID_CONTA_EMPRESA = ?""",
            (id_folha, contexto['id_conta'])
        )
        folha = cursor.fetchone()

        if not folha:
            return jsonify({'mensagem': 'Folha não encontrada'}), 404

        cursor.execute(
            """SELECT ID_FOLHA_ITEM, ID_FUNCIONARIO, ID_CONTA_DESTINO,
                      CPF, NOME, VALOR, STATUS, ERRO,
                      ID_MOVIMENTACAO, DATA_PAGAMENTO
               FROM FOLHA_ITEM
               WHERE ID_FOLHA = ?
               ORDER BY NOME""",
            (id_folha,)
        )

        itens = []
        total = 0.0
        total_valido = 0.0
        total_pendente = 0.0
        total_pago = 0.0

        for item in cursor.fetchall():
            valor = float(item[5] or 0)
            status_item = int(item[6] or 0)
            total += valor

            if status_item == 0:
                total_pendente += valor
            elif status_item == 1:
                total_valido += valor
            elif status_item == 2:
                total_pago += valor

            itens.append({
                'id_item': item[0],
                'id_funcionario': item[1],
                'nome': item[4],
                'cpf_mascarado': mascarar_cpf_mcp(item[3]),
                'valor': valor,
                'status': status_item,
                'status_nome': STATUS_ITEM_FOLHA_MCP.get(
                    status_item,
                    'DESCONHECIDO'
                ),
                'possui_conta_destino': item[2] is not None,
                'erro': item[7],
                'id_movimentacao': item[8],
                'data_pagamento': str(item[9]) if item[9] else None
            })

        status_folha = int(folha[3] or 0)

        return jsonify({
            'id_folha': folha[0],
            'mes': folha[1],
            'ano': folha[2],
            'status': status_folha,
            'status_nome': STATUS_FOLHA_MCP.get(
                status_folha,
                'DESCONHECIDO'
            ),
            'data_criacao': str(folha[4]) if folha[4] else None,
            'data_pagamento': str(folha[5]) if folha[5] else None,
            'total': round(total, 2),
            'total_valido': round(total_valido, 2),
            'total_pendente': round(total_pendente, 2),
            'total_pago': round(total_pago, 2),
            'quantidade_funcionarios': len(itens),
            'quantidade_validos': sum(
                1 for item in itens if item['status'] == 1
            ),
            'quantidade_pendentes': sum(
                1 for item in itens if item['status'] == 0
            ),
            'quantidade_pagos': sum(
                1 for item in itens if item['status'] == 2
            ),
            'itens': itens
        }), 200

    except Exception as e:
        print('ERRO MCP CONSULTAR FOLHA:', e)
        return jsonify({'mensagem': 'Erro ao consultar folha'}), 500

    finally:
        if cursor:
            cursor.close()
