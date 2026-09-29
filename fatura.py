from datetime import date, datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

from main import app
from banco import con


FUSO_BRASIL = ZoneInfo('America/Sao_Paulo')


def hoje_brasil():
    return datetime.now(FUSO_BRASIL).date()


def calcular_vencimento(data_fechamento, dia_vencimento):
    ano = data_fechamento.year
    mes = data_fechamento.month

    if dia_vencimento <= data_fechamento.day:
        mes += 1

        if mes == 13:
            mes = 1
            ano += 1

    return date(ano, mes, dia_vencimento)


def fechar_fatura(id_cartao):
    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("""
            SELECT FECHAMENTO, DIA_VENCIMENTO, ID_CONTA
            FROM CARTAO
            WHERE ID_CARTAO = ?
        """, (id_cartao,))

        cartao = cursor.fetchone()

        if not cartao:
            return

        dia_fechamento = cartao[0]
        dia_vencimento = cartao[1]
        id_conta = cartao[2]
        hoje = hoje_brasil()

        if dia_fechamento != hoje.day:
            return

        data_fechamento = hoje
        data_vencimento = calcular_vencimento(data_fechamento, dia_vencimento)

        cursor.execute("""
            SELECT ID_FATURA
            FROM FATURA
            WHERE ID_CONTA = ?
            AND DATA_FECHAMENTO = ?
        """, (id_conta, data_fechamento))

        if cursor.fetchone():
            return

        cursor.execute("""
            SELECT FC.ID_FATURA_COMPRA, FC.VALOR_PARCELA
            FROM FATURA_COMPRA FC
            INNER JOIN COMPRA C ON C.ID_COMPRA = FC.ID_COMPRA
            WHERE C.ID_CARTAO = ?
            AND FC.STATUS = 0
            AND FC.ID_FATURA IS NULL
            AND FC.DATA_PARCELA <= ?
        """, (id_cartao, data_fechamento))

        parcelas = cursor.fetchall()

        if not parcelas:
            return

        valor_total = sum(parcela[1] for parcela in parcelas)

        cursor.execute("""
            INSERT INTO FATURA (
                ID_CONTA, VALOR_TOTAL, STATUS,
                DATA_FECHAMENTO, DATA_VENCIMENTO
            )
            VALUES (?, ?, 0, ?, ?)
            RETURNING ID_FATURA
        """, (id_conta, valor_total, data_fechamento, data_vencimento))

        id_fatura = cursor.fetchone()[0]

        for parcela in parcelas:
            cursor.execute("""
                UPDATE FATURA_COMPRA
                SET ID_FATURA = ?
                WHERE ID_FATURA_COMPRA = ?
            """, (id_fatura, parcela[0]))

        con.commit()

        print('Fatura fechada:', id_fatura, 'conta:', id_conta, 'valor:', valor_total)

    except Exception as e:
        con.rollback()
        print('Erro ao fechar fatura:', e)

    finally:
        if cursor:
            cursor.close()


def verificar_fechamento():
    hoje = hoje_brasil()
    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("""
            SELECT ID_CARTAO
            FROM CARTAO
            WHERE FECHAMENTO = ?
            AND STATUS = 0
        """, (hoje.day,))

        cartoes = cursor.fetchall()

    finally:
        if cursor:
            cursor.close()

    for cartao in cartoes:
        fechar_fatura(cartao[0])


def executar_com_contexto():
    with app.app_context():
        verificar_fechamento()


scheduler = BackgroundScheduler(timezone=FUSO_BRASIL)

scheduler.add_job(
    executar_com_contexto,
    'cron',
    minute='*/5',
    id='fechamento_fatura',
    replace_existing=True
)

scheduler.start()

try:
    executar_com_contexto()
except Exception as e:
    print('Erro na verificacao inicial das faturas:', e)
