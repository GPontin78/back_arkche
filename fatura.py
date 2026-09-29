import os
from datetime import date
from apscheduler.schedulers.background import BackgroundScheduler

from main import app
from banco import con


def fechar_fatura(id_cartao):

    try:

        cursor = con.cursor()

        cursor.execute("""
            SELECT
                FECHAMENTO,
                DIA_VENCIMENTO,
                ID_CONTA
            FROM CARTAO
            WHERE ID_CARTAO = ?
        """, (id_cartao,))

        cartao = cursor.fetchone()

        if not cartao:
            return

        dia_fechamento = cartao[0]
        dia_vencimento = cartao[1]
        id_conta = cartao[2]

        hoje = date.today()

        data_fechamento = date(
            hoje.year,
            hoje.month,
            dia_fechamento
        )

        data_vencimento = date(
            hoje.year,
            hoje.month,
            dia_vencimento
        )

        cursor.execute("""
            SELECT ID_FATURA
            FROM FATURA
            WHERE ID_CONTA = ?
            AND DATA_FECHAMENTO = ?
        """, (
            id_conta,
            data_fechamento
        ))

        fatura_existente = cursor.fetchone()

        if fatura_existente:
            return

        cursor.execute("""
            SELECT
                FC.ID_FATURA_COMPRA,
                FC.VALOR_PARCELA
            FROM FATURA_COMPRA FC

            INNER JOIN COMPRA C
            ON C.ID_COMPRA = FC.ID_COMPRA

            WHERE C.ID_CARTAO = ?
            AND FC.STATUS = 0
            AND FC.ID_FATURA IS NULL
            AND FC.DATA_PARCELA <= ?
        """, (
            id_cartao,
            data_fechamento
        ))

        parcelas = cursor.fetchall()

        if not parcelas:
            return

        valor_total = 0

        for parcela in parcelas:

            valor_parcela = parcela[1]

            valor_total = valor_total + valor_parcela

        cursor.execute("""
            INSERT INTO FATURA (
                ID_CONTA,
                VALOR_TOTAL,
                STATUS,
                DATA_FECHAMENTO,
                DATA_VENCIMENTO
            )
            VALUES (?, ?, 0, ?, ?)
            RETURNING ID_FATURA
        """, (
            id_conta,
            valor_total,
            data_fechamento,
            data_vencimento
        ))

        id_fatura = cursor.fetchone()[0]

        for parcela in parcelas:

            id_fatura_compra = parcela[0]

            cursor.execute("""
                UPDATE FATURA_COMPRA
                SET ID_FATURA = ?
                WHERE ID_FATURA_COMPRA = ?
            """, (
                id_fatura,
                id_fatura_compra
            ))

        con.commit()

    except Exception as e:

        con.rollback()

        print('Erro ao fechar fatura:', e)


def verificar_fechamento():

    hoje = date.today()

    cursor = con.cursor()

    cursor.execute("""
        SELECT ID_CARTAO
        FROM CARTAO
        WHERE FECHAMENTO = ?
        AND STATUS = 0
    """, (hoje.day,))

    cartoes = cursor.fetchall()

    for cartao in cartoes:

        id_cartao = cartao[0]

        fechar_fatura(id_cartao)


def executar_com_contexto(funcao):

    with app.app_context():

        funcao()


scheduler = BackgroundScheduler()

scheduler.add_job(
    lambda: executar_com_contexto(verificar_fechamento),
    'cron',
    hour=0,
    minute=0,
    id='fechamento_fatura',
    replace_existing=True
)


if os.environ.get("WERKZEUG_RUN_MAIN") == "true":

    scheduler.start()