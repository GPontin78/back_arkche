from calendar import monthrange
from datetime import date, datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from flask import jsonify

from main import app
from banco import con
from funcao import descobre_id_conta

FUSO_BRASIL = ZoneInfo('America/Sao_Paulo')


def hoje_brasil():
    return datetime.now(FUSO_BRASIL).date()


def data_no_mes(ano, mes, dia):
    return date(ano, mes, min(int(dia), monthrange(ano, mes)[1]))


def deslocar_mes(ano, mes, quantidade):
    indice = ano * 12 + (mes - 1) + quantidade
    return indice // 12, indice % 12 + 1


def fechamento_mais_recente(referencia, dia_fechamento):
    fechamento = data_no_mes(referencia.year, referencia.month, dia_fechamento)

    if fechamento <= referencia:
        return fechamento

    ano, mes = deslocar_mes(referencia.year, referencia.month, -1)
    return data_no_mes(ano, mes, dia_fechamento)


def data_vencimento_fatura(data_fechamento, dia_vencimento):
    ano = data_fechamento.year
    mes = data_fechamento.month

    if int(dia_vencimento) <= data_fechamento.day:
        ano, mes = deslocar_mes(ano, mes, 1)

    return data_no_mes(ano, mes, dia_vencimento)


def projetar_fechamento(data_parcela, dia_fechamento):
    fechamento = data_no_mes(data_parcela.year, data_parcela.month, dia_fechamento)

    if data_parcela <= fechamento:
        return fechamento

    ano, mes = deslocar_mes(data_parcela.year, data_parcela.month, 1)
    return data_no_mes(ano, mes, dia_fechamento)


def situacao_fatura(status, data_vencimento):
    if int(status or 0) == 1:
        return 'PAGA'

    if data_vencimento and data_vencimento < hoje_brasil():
        return 'VENCIDA'

    return 'FECHADA'


def fechar_fatura(id_cartao, data_fechamento=None):
    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("""
            SELECT FECHAMENTO, DIA_VENCIMENTO, ID_CONTA, STATUS
            FROM CARTAO
            WHERE ID_CARTAO = ?
        """, (id_cartao,))

        cartao = cursor.fetchone()

        if not cartao or int(cartao[3] or 0) != 0:
            return None

        dia_fechamento = int(cartao[0])
        dia_vencimento = int(cartao[1])
        id_conta = cartao[2]

        if data_fechamento is None:
            data_fechamento = fechamento_mais_recente(hoje_brasil(), dia_fechamento)

        data_vencimento = data_vencimento_fatura(data_fechamento, dia_vencimento)

        cursor.execute("""
            SELECT ID_FATURA
            FROM FATURA
            WHERE ID_CONTA = ? AND DATA_FECHAMENTO = ?
        """, (id_conta, data_fechamento))

        existente = cursor.fetchone()
        id_fatura = existente[0] if existente else None

        cursor.execute("""
            SELECT FC.ID_FATURA_COMPRA, FC.VALOR_PARCELA
            FROM FATURA_COMPRA FC
            INNER JOIN COMPRA C ON C.ID_COMPRA = FC.ID_COMPRA
            WHERE C.ID_CARTAO = ?
              AND FC.STATUS = 0
              AND FC.ID_FATURA IS NULL
              AND FC.DATA_PARCELA <= ?
            ORDER BY FC.DATA_PARCELA, FC.ID_FATURA_COMPRA
        """, (id_cartao, data_fechamento))

        parcelas = cursor.fetchall()

        if not parcelas and id_fatura is None:
            return None

        if id_fatura is None:
            valor_total = sum(parcela[1] for parcela in parcelas)

            cursor.execute("""
                INSERT INTO FATURA (
                    ID_CONTA, VALOR_TOTAL, STATUS, DATA_FECHAMENTO, DATA_VENCIMENTO
                )
                VALUES (?, ?, 0, ?, ?)
                RETURNING ID_FATURA
            """, (id_conta, valor_total, data_fechamento, data_vencimento))

            id_fatura = cursor.fetchone()[0]

        for id_fatura_compra, _valor in parcelas:
            cursor.execute("""
                UPDATE FATURA_COMPRA
                SET ID_FATURA = ?
                WHERE ID_FATURA_COMPRA = ? AND ID_FATURA IS NULL
            """, (id_fatura, id_fatura_compra))

        if parcelas:
            cursor.execute("""
                SELECT CAST(COALESCE(SUM(VALOR_PARCELA), 0) AS DECIMAL(18,2))
                FROM FATURA_COMPRA
                WHERE ID_FATURA = ?
            """, (id_fatura,))

            valor_total = cursor.fetchone()[0]

            cursor.execute("""
                UPDATE FATURA
                SET VALOR_TOTAL = ?, DATA_VENCIMENTO = ?
                WHERE ID_FATURA = ?
            """, (valor_total, data_vencimento, id_fatura))

            con.commit()

            print(
                'Fatura atualizada:',
                'conta=', id_conta,
                'fatura=', id_fatura,
                'parcelas_adicionadas=', len(parcelas),
                'valor=', valor_total,
                'fechamento=', data_fechamento,
                'vencimento=', data_vencimento
            )

        return id_fatura

    except Exception as e:
        con.rollback()
        print('Erro ao fechar fatura:', e)
        return None

    finally:
        if cursor:
            cursor.close()


def verificar_fechamento():
    hoje = hoje_brasil()
    cursor = None

    try:
        cursor = con.cursor()
        cursor.execute("""
            SELECT ID_CARTAO, FECHAMENTO
            FROM CARTAO
            WHERE STATUS = 0
        """)
        cartoes = cursor.fetchall()

    finally:
        if cursor:
            cursor.close()

    for id_cartao, dia_fechamento in cartoes:
        data_fechamento = fechamento_mais_recente(hoje, int(dia_fechamento))
        fechar_fatura(id_cartao, data_fechamento)


def serializar_item_fatura(linha):
    return {
        'id_fatura_compra': linha[5],
        'id_compra': linha[6],
        'numero_parcela': int(linha[7] or 0),
        'total_parcelas': int(linha[8] or 1),
        'valor': float(linha[9] or 0),
        'status': int(linha[10] or 0),
        'data_parcela': str(linha[11]) if linha[11] else None,
        'data_compra': str(linha[12]) if linha[12] else None,
        'valor_compra': float(linha[13] or 0)
    }


@app.route('/cartao/faturas', methods=['GET'])
def listar_faturas_cartao():
    id_conta = descobre_id_conta()

    if id_conta is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("""
            SELECT ID_CARTAO, FECHAMENTO, DIA_VENCIMENTO
            FROM CARTAO
            WHERE ID_CONTA = ?
        """, (id_conta,))

        cartao = cursor.fetchone()

        if not cartao:
            return jsonify({
                'faturas': [],
                'proximas_faturas': [],
                'fatura_atual': None,
                'proxima_fatura': None
            }), 200

        id_cartao = cartao[0]
        dia_fechamento = int(cartao[1])
        dia_vencimento = int(cartao[2])

        cursor.close()
        cursor = None

        fechamento_referencia = fechamento_mais_recente(hoje_brasil(), dia_fechamento)
        fechar_fatura(id_cartao, fechamento_referencia)

        cursor = con.cursor()
        cursor.execute("""
            SELECT
                F.ID_FATURA,
                F.VALOR_TOTAL,
                F.STATUS,
                F.DATA_FECHAMENTO,
                F.DATA_VENCIMENTO,
                FC.ID_FATURA_COMPRA,
                C.ID_COMPRA,
                FC.NUMERO_PARCELA,
                C.QTD_PARCELA,
                FC.VALOR_PARCELA,
                FC.STATUS,
                FC.DATA_PARCELA,
                C.DATA_COMPRA,
                C.VALOR_COMPRA
            FROM FATURA F
            LEFT JOIN FATURA_COMPRA FC ON FC.ID_FATURA = F.ID_FATURA
            LEFT JOIN COMPRA C ON C.ID_COMPRA = FC.ID_COMPRA
            WHERE F.ID_CONTA = ?
            ORDER BY F.DATA_FECHAMENTO DESC, F.ID_FATURA DESC, FC.DATA_PARCELA, FC.ID_FATURA_COMPRA
        """, (id_conta,))

        linhas = cursor.fetchall()
        faturas_por_id = {}
        faturas = []

        for linha in linhas:
            id_fatura = linha[0]

            if id_fatura not in faturas_por_id:
                fatura = {
                    'id_fatura': id_fatura,
                    'valor_total': float(linha[1] or 0),
                    'status': int(linha[2] or 0),
                    'situacao': situacao_fatura(linha[2], linha[4]),
                    'data_fechamento': str(linha[3]) if linha[3] else None,
                    'data_vencimento': str(linha[4]) if linha[4] else None,
                    'itens': []
                }
                faturas_por_id[id_fatura] = fatura
                faturas.append(fatura)

            if linha[5] is not None:
                faturas_por_id[id_fatura]['itens'].append(serializar_item_fatura(linha))

        cursor.execute("""
            SELECT
                FC.ID_FATURA_COMPRA,
                C.ID_COMPRA,
                FC.NUMERO_PARCELA,
                C.QTD_PARCELA,
                FC.VALOR_PARCELA,
                FC.STATUS,
                FC.DATA_PARCELA,
                C.DATA_COMPRA,
                C.VALOR_COMPRA
            FROM FATURA_COMPRA FC
            INNER JOIN COMPRA C ON C.ID_COMPRA = FC.ID_COMPRA
            WHERE C.ID_CARTAO = ?
              AND FC.ID_FATURA IS NULL
              AND FC.STATUS = 0
            ORDER BY FC.DATA_PARCELA, FC.ID_FATURA_COMPRA
        """, (id_cartao,))

        parcelas_futuras = cursor.fetchall()
        projecoes_por_data = {}

        for linha in parcelas_futuras:
            data_parcela = linha[6]

            if not data_parcela:
                continue

            data_fechamento = projetar_fechamento(data_parcela, dia_fechamento)
            chave = data_fechamento.isoformat()

            if chave not in projecoes_por_data:
                projecoes_por_data[chave] = {
                    'data_fechamento': chave,
                    'data_vencimento': data_vencimento_fatura(data_fechamento, dia_vencimento).isoformat(),
                    'valor_total': 0.0,
                    'situacao': 'PREVISTA',
                    'itens': []
                }

            item = {
                'id_fatura_compra': linha[0],
                'id_compra': linha[1],
                'numero_parcela': int(linha[2] or 0),
                'total_parcelas': int(linha[3] or 1),
                'valor': float(linha[4] or 0),
                'status': int(linha[5] or 0),
                'data_parcela': str(linha[6]) if linha[6] else None,
                'data_compra': str(linha[7]) if linha[7] else None,
                'valor_compra': float(linha[8] or 0)
            }

            projecoes_por_data[chave]['itens'].append(item)
            projecoes_por_data[chave]['valor_total'] += item['valor']

        proximas_faturas = sorted(
            projecoes_por_data.values(),
            key=lambda fatura: fatura['data_fechamento']
        )

        for fatura in proximas_faturas:
            fatura['valor_total'] = round(fatura['valor_total'], 2)

        return jsonify({
            'faturas': faturas,
            'proximas_faturas': proximas_faturas,
            'fatura_atual': faturas[0] if faturas else None,
            'proxima_fatura': proximas_faturas[0] if proximas_faturas else None
        }), 200

    except Exception as e:
        return jsonify({'mensagem': 'Erro ao buscar faturas do cartao', 'erro': str(e)}), 500

    finally:
        if cursor:
            cursor.close()


def executar_com_contexto(funcao):
    with app.app_context():
        funcao()


scheduler = BackgroundScheduler(timezone=FUSO_BRASIL)

scheduler.add_job(
    lambda: executar_com_contexto(verificar_fechamento),
    'cron',
    minute='*/5',
    id='fechamento_fatura',
    replace_existing=True,
    coalesce=True,
    misfire_grace_time=3600
)


def iniciar_scheduler_faturas():
    if scheduler.running:
        return

    scheduler.start()
    print('Scheduler de faturas iniciado - America/Sao_Paulo - verificacao a cada 5 minutos')

    try:
        executar_com_contexto(verificar_fechamento)
    except Exception as e:
        print('Erro na verificacao inicial de faturas:', e)


iniciar_scheduler_faturas()
