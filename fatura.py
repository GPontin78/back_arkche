from datetime import date, datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

from main import app
from banco import con


FUSO_BRASIL = ZoneInfo('America/Sao_Paulo')


def fechar_fatura(id_cartao):

    cursor = None

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
            con.rollback()
            return

        dia_fechamento = cartao[0]
        dia_vencimento = cartao[1]
        id_conta = cartao[2]

        hoje = datetime.now(FUSO_BRASIL).date()

        data_fechamento = date(
            hoje.year,
            hoje.month,
            dia_fechamento
        )

        ano_vencimento = hoje.year
        mes_vencimento = hoje.month

        if dia_vencimento <= dia_fechamento:
            mes_vencimento = mes_vencimento + 1

            if mes_vencimento == 13:
                mes_vencimento = 1
                ano_vencimento = ano_vencimento + 1

        data_vencimento = date(
            ano_vencimento,
            mes_vencimento,
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
            cursor.execute("""
                UPDATE FATURA
                SET DATA_VENCIMENTO = ?
                WHERE ID_FATURA = ?
            """, (
                data_vencimento,
                fatura_existente[0]
            ))

            con.commit()
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
            con.rollback()
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

        if cursor is not None:
            con.rollback()

        print('Erro ao fechar fatura:', e)

    finally:

        if cursor is not None:
            cursor.close()


def verificar_fechamento():

    hoje = datetime.now(FUSO_BRASIL).date()
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
        con.rollback()

    finally:

        if cursor is not None:
            cursor.close()

    for cartao in cartoes:

        id_cartao = cartao[0]
        fechar_fatura(id_cartao)


def executar_com_contexto(funcao):
    with app.app_context():
        funcao()
        
scheduler = BackgroundScheduler(timezone=FUSO_BRASIL)
scheduler.add_job(
    executar_com_contexto,
    'cron',
    args=[verificar_fechamento],
    minute='*/5',
    id='fechamento_fatura',
    replace_existing=True,
    max_instances=1,
    coalesce=True,
    next_run_time=datetime.now(FUSO_BRASIL)
)
scheduler.start()
