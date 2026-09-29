from flask import jsonify, request
from main import app
from banco import con
from funcao import *


def formatar_numero_cartao(numero):
    numero = str(numero or '')
    return ' '.join(numero[i:i + 4] for i in range(0, len(numero), 4))


def serializar_cartao(cartao):
    limite_total = float(cartao[5] or 0)
    limite_utilizado = calcular_limite_cartao(cartao[0])

    return {
        'id_cartao': cartao[0],
        'id_conta': cartao[1],
        'numero_cartao': str(cartao[2]),
        'numero_formatado': formatar_numero_cartao(cartao[2]),
        'vencimento': str(cartao[3]) if cartao[3] else None,
        'cvv': str(cartao[4]) if cartao[4] is not None else None,
        'limite_total': limite_total,
        'limite_utilizado': limite_utilizado,
        'limite_disponivel': limite_total - limite_utilizado,
        'dia_vencimento': cartao[6],
        'dia_fechamento': cartao[7]
    }


@app.route('/cartao', methods=['GET'])
def buscar_cartao():
    id_conta = descobre_id_conta()

    if id_conta is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("""SELECT ID_CARTAO, ID_CONTA, NUMERO_CARTAO, VENCIMENTO, CVV, LIMITE, DIA_VENCIMENTO, FECHAMENTO
                          FROM CARTAO
                          WHERE ID_CONTA = ?""", (id_conta,))

        cartao = cursor.fetchone()

        if not cartao:
            return jsonify({'possui_cartao': False, 'cartao': None}), 200

        return jsonify({'possui_cartao': True, 'cartao': serializar_cartao(cartao)}), 200

    except Exception as e:
        return jsonify({'mensagem': 'Erro ao buscar cartao', 'erro': str(e)}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/cartao/compras', methods=['GET'])
def listar_compras_cartao():
    id_conta = descobre_id_conta()

    if id_conta is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("SELECT ID_CARTAO FROM CARTAO WHERE ID_CONTA = ?", (id_conta,))
        cartao = cursor.fetchone()

        if not cartao:
            return jsonify({
                'compras': [],
                'parcelas': [],
                'resumo': {
                    'compras_credito': 0,
                    'parcelas_pendentes': 0,
                    'valor_pendente': 0.0,
                    'proxima_parcela': None
                }
            }), 200

        id_cartao = cartao[0]

        cursor.execute("""
            SELECT
                C.ID_COMPRA,
                C.VALOR_COMPRA,
                C.VALOR_PARCELA,
                C.QTD_PARCELA,
                C.DATA_COMPRA,
                FC.ID_FATURA_COMPRA,
                FC.NUMERO_PARCELA,
                FC.STATUS,
                FC.VALOR_PARCELA,
                FC.DATA_PARCELA,
                FC.ID_FATURA,
                F.STATUS,
                F.DATA_FECHAMENTO,
                F.DATA_VENCIMENTO
            FROM COMPRA C
            LEFT JOIN FATURA_COMPRA FC ON FC.ID_COMPRA = C.ID_COMPRA
            LEFT JOIN FATURA F ON F.ID_FATURA = FC.ID_FATURA
            WHERE C.ID_CARTAO = ?
              AND C.TIPO = 1
            ORDER BY C.DATA_COMPRA DESC, FC.NUMERO_PARCELA
        """, (id_cartao,))

        linhas = cursor.fetchall()
        compras_por_id = {}
        compras = []
        parcelas = []

        for linha in linhas:
            id_compra = linha[0]

            if id_compra not in compras_por_id:
                compra = {
                    'id_compra': id_compra,
                    'valor_total': float(linha[1] or 0),
                    'valor_parcela': float(linha[2] or 0),
                    'qtd_parcelas': int(linha[3] or 1),
                    'data_compra': str(linha[4]) if linha[4] else None,
                    'parcelas': []
                }
                compras_por_id[id_compra] = compra
                compras.append(compra)

            if linha[5] is None:
                continue

            parcela = {
                'id_fatura_compra': linha[5],
                'id_compra': id_compra,
                'numero': int(linha[6] or 0),
                'total_parcelas': int(linha[3] or 1),
                'status': int(linha[7] or 0),
                'valor': float(linha[8] or 0),
                'data_parcela': str(linha[9]) if linha[9] else None,
                'id_fatura': linha[10],
                'status_fatura': int(linha[11]) if linha[11] is not None else None,
                'data_fechamento': str(linha[12]) if linha[12] else None,
                'data_vencimento': str(linha[13]) if linha[13] else None,
                'data_compra': str(linha[4]) if linha[4] else None
            }

            compras_por_id[id_compra]['parcelas'].append(parcela)
            parcelas.append(parcela)

        parcelas_pendentes = [parcela for parcela in parcelas if parcela['status'] == 0]
        parcelas_pendentes_ordenadas = sorted(
            parcelas_pendentes,
            key=lambda parcela: parcela['data_parcela'] or '9999-12-31'
        )

        proxima_parcela = parcelas_pendentes_ordenadas[0] if parcelas_pendentes_ordenadas else None

        return jsonify({
            'compras': compras,
            'parcelas': parcelas,
            'resumo': {
                'compras_credito': len(compras),
                'parcelas_pendentes': len(parcelas_pendentes),
                'valor_pendente': round(sum(parcela['valor'] for parcela in parcelas_pendentes), 2),
                'proxima_parcela': proxima_parcela
            }
        }), 200

    except Exception as e:
        return jsonify({'mensagem': 'Erro ao buscar compras do cartao', 'erro': str(e)}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/adicionar_cartao', methods=['POST'])
def adicionar_cartao():
    try:
        dados = request.get_json() or {}

        dia_vencimento = dados.get('dia_vencimento', 10)
        dia_fechamento = dados.get('dia_fechamento', 3)

        id_conta = descobre_id_conta()

        if id_conta is None:
            return jsonify({'mensagem': 'Usuario nao logado'}), 403

        cursor = con.cursor()

        cursor.execute("""SELECT ID_CARTAO, ID_CONTA, NUMERO_CARTAO, VENCIMENTO, CVV, LIMITE, DIA_VENCIMENTO, FECHAMENTO
                          FROM CARTAO
                          WHERE ID_CONTA = ?""", (id_conta,))

        cartao_existente = cursor.fetchone()

        if cartao_existente:
            return jsonify({
                'mensagem': 'Esta conta ja possui cartao',
                'possui_cartao': True,
                'cartao': serializar_cartao(cartao_existente)
            }), 409

        cvv = gerar_cvv()
        numero_cartao = gerar_numero_cartao()

        cursor.execute("""SELECT 1 FROM CARTAO WHERE NUMERO_CARTAO = ?""", (numero_cartao,))

        resultado = cursor.fetchone()

        if resultado:
            return jsonify({'mensagem': 'Numero de cartao ja existe'}), 400

        limite = float(5000)
        vencimento = gerar_vencimento()

        cursor.execute("""INSERT INTO CARTAO(ID_CONTA, NUMERO_CARTAO, VENCIMENTO, CVV, LIMITE, DIA_VENCIMENTO, FECHAMENTO)
                          VALUES (?, ?, ?, ?, ?, ?, ?)""",
                       (id_conta, numero_cartao, vencimento, cvv, limite, dia_vencimento, dia_fechamento))

        con.commit()

        cursor.execute("""SELECT ID_CARTAO, ID_CONTA, NUMERO_CARTAO, VENCIMENTO, CVV, LIMITE, DIA_VENCIMENTO, FECHAMENTO
                          FROM CARTAO
                          WHERE ID_CONTA = ? AND NUMERO_CARTAO = ?""", (id_conta, numero_cartao))

        cartao = cursor.fetchone()

        return jsonify({
            'mensagem': 'Cartao adicionado com sucesso',
            'possui_cartao': True,
            'cartao': serializar_cartao(cartao)
        }), 201

    except Exception as e:
        con.rollback()
        return jsonify({'mensagem': 'Erro ao adicionar cartao', 'erro': str(e)}), 500

    finally:
        if 'cursor' in locals() and cursor:
            cursor.close()


@app.route('/bloquear_cartao', methods=['PUT'])
def bloquear_cartao():
    try:
        id_conta = descobre_id_conta()

        if id_conta is None:
            return jsonify({'mensagem': 'Usuario nao logado'}), 403

        cursor = con.cursor()

        cursor.execute("""SELECT ID_CARTAO, STATUS
                          FROM CARTAO
                          WHERE ID_CONTA = ?""", (id_conta,))

        cartao = cursor.fetchone()

        if not cartao:
            return jsonify({'mensagem': 'Cartao nao encontrado'}), 404

        id_cartao = cartao[0]
        status = cartao[1]

        if status == 0:
            status = 1

        else:
            status = 0

        cursor.execute("""UPDATE CARTAO
                          SET STATUS = ?
                          WHERE ID_CARTAO = ?""",
                       (status, id_cartao))

        con.commit()

        return jsonify({
            'mensagem': 'Status do cartao alterado com sucesso',
            'status': status
        }), 200

    except Exception as e:
        con.rollback()

        return jsonify({
            'mensagem': 'Erro ao alterar status do cartao',
            'erro': str(e)
        }), 500

    finally:
        if 'cursor' in locals() and cursor:
            cursor.close()