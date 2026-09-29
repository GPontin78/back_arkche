from datetime import date
from apscheduler.schedulers.background import BackgroundScheduler

from main import app
from banco import con


def data_vencimento_fatura(hoje, dia_fechamento, dia_vencimento):
    ano = hoje.year
    mes = hoje.month

    if dia_vencimento <= dia_fechamento:
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

        data_vencimento = data_vencimento_fatura(
            hoje,
            dia_fechamento,
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
            valor_total = valor_total + parcela[1]

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
            cursor.execute("""
                UPDATE FATURA_COMPRA
                SET ID_FATURA = ?
                WHERE ID_FATURA_COMPRA = ?
            """, (
                id_fatura,
                parcela[0]
            ))

        con.commit()

        print(
            'Fatura fechada:',
            'conta=', id_conta,
            'fatura=', id_fatura,
            'valor=', valor_total,
            'fechamento=', data_fechamento,
            'vencimento=', data_vencimento
        )

    except Exception as e:
        con.rollback()
        print('Erro ao fechar fatura:', e)

    finally:
        if cursor:
            cursor.close()


def verificar_fechamento():
    hoje = date.today()
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


def executar_com_contexto(funcao):
    with app.app_context():
        funcao()


scheduler = BackgroundScheduler(timezone='America/Sao_Paulo')

scheduler.add_job(
    lambda: executar_com_contexto(verificar_fechamento),
    'cron',
    hour=11,
    minute=19,
    id='fechamento_fatura',
    replace_existing=True,
    coalesce=True,
    misfire_grace_time=3600
)


def iniciar_scheduler_faturas():
    if scheduler.running:
        return

    scheduler.start()
    print('Scheduler de faturas iniciado - America/Sao_Paulo - fechamento diario 11:19')

    try:
        executar_com_contexto(verificar_fechamento)
    except Exception as e:
        print('Erro na verificacao inicial de faturas:', e)


iniciar_scheduler_faturas()
