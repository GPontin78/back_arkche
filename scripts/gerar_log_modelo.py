"""Triggers no modelo direto: variáveis, valores posicionais e conexão externa."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.gerar_log_tres_triggers import OPERACOES
from scripts.gerar_migracao_log import CAMPOS,TABELAS_PRINCIPAIS,texto_sql


def valores(tabela,registro):
    return " || ' - ' ||\n        ".join(
        f"COALESCE(CAST({registro}.{campo} AS VARCHAR(80)), '')"
        for campo in CAMPOS[tabela].split()
    )


def gerar_trigger(tabela,operacao,destino='__LOG_DATA_SOURCE__',usuario='__LOG_USUARIO__',senha='__LOG_SENHA__',sem_complementos=True):
    chave = CAMPOS[tabela].split()[0]
    if operacao == 'INSERT':
        sigla = 'AI'
        registro = 'NEW'
        declaracoes = 'DECLARE VARIABLE V_NOVO VARCHAR(2000);'
        atribuicoes = f"    V_NOVO =\n        {valores(tabela,'NEW')};"
        anterior,novo = 'NULL',':V_NOVO'
    elif operacao == 'UPDATE':
        sigla = 'AU'
        registro = 'NEW'
        declaracoes = 'DECLARE VARIABLE V_ANTIGO VARCHAR(2000);\nDECLARE VARIABLE V_NOVO VARCHAR(2000);'
        atribuicoes = f"    V_ANTIGO =\n        {valores(tabela,'OLD')};\n\n    V_NOVO =\n        {valores(tabela,'NEW')};"
        anterior,novo = ':V_ANTIGO',':V_NOVO'
    elif operacao == 'DELETE':
        sigla = 'AD'
        registro = 'OLD'
        declaracoes = 'DECLARE VARIABLE V_ANTIGO VARCHAR(2000);'
        atribuicoes = f"    V_ANTIGO =\n        {valores(tabela,'OLD')};"
        anterior,novo = ':V_ANTIGO','NULL'
    else:
        raise ValueError('Operação de trigger inválida')
    cabecalho = f'AFTER {operacao}'
    transacao = ''
    if not sem_complementos:
        # Somente para conferir a versão 017 já instalada.
        cabecalho = f'ACTIVE AFTER {operacao} POSITION 32000'
        transacao = '\n    WITH COMMON TRANSACTION'
    return f'''CREATE OR ALTER TRIGGER TG_{sigla}_{tabela}_LOG
FOR {tabela}
{cabecalho}
AS
DECLARE VARIABLE V_USUARIO VARCHAR(100);
{declaracoes}
BEGIN
    V_USUARIO = COALESCE(
        RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_USUARIO_LOG'),
        RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_ID_USUARIO'),
        CURRENT_USER
    );

    -- {' - '.join(CAMPOS[tabela].split())}
{atribuicoes}

    EXECUTE STATEMENT
    (
        'INSERT INTO LOG
        (
            USUARIO,
            DATA_HORA,
            TABELA,
            ID_REGISTRO,
            ACAO,
            VALOR_ANTERIOR,
            VALOR_NOVO
        )
        VALUES (?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?)'
    )
    (
        :V_USUARIO,
        '{tabela}',
        {registro}.{chave},
        '{operacao}',
        {anterior},
        {novo}
    )
    ON EXTERNAL DATA SOURCE {texto_sql(destino)}
    AS USER {texto_sql(usuario)}
    PASSWORD {texto_sql(senha)}{transacao};
END^
'''


def main():
    sql = ['/* O aplicador preenche a conexão já configurada, sem publicar credenciais. */',
           'SET BAIL ON;','SET AUTODDL OFF;','SET TERM ^;']
    for tabela in TABELAS_PRINCIPAIS:
        for _,operacao,_ in OPERACOES:
            sql.append(gerar_trigger(tabela,operacao))
    sql.extend(['SET TERM ;^','COMMIT;'])
    caminho = ROOT/'migrations/018_log_sem_complementos.sql'
    caminho.write_text('\n'.join(sql),encoding='utf-8')
    print(caminho)


if __name__ == '__main__':
    main()
