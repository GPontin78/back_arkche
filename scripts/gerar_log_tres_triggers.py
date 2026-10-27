"""Três triggers por tabela: uma para INSERT, uma para UPDATE e uma para DELETE."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.gerar_log_texto import resumo
from scripts.gerar_migracao_log import CAMPOS,TABELAS_PRINCIPAIS

OPERACOES = (('AI','INSERT',2),('AU','UPDATE',4),('AD','DELETE',6))


def gerar_trigger(tabela,operacao):
    chave = CAMPOS[tabela].split()[0]
    if operacao == 'INSERT':
        sigla = 'AI'
        registro = 'NEW'
        valores = 'NULL, :novo'
        parametros = f"novo := {resumo(tabela,'NEW')}"
    elif operacao == 'UPDATE':
        sigla = 'AU'
        registro = 'NEW'
        valores = ':antes, :novo'
        parametros = f"antes := {resumo(tabela,'OLD')},\n        novo := {resumo(tabela,'NEW')}"
    elif operacao == 'DELETE':
        sigla = 'AD'
        registro = 'OLD'
        valores = ':antes, NULL'
        parametros = f"antes := {resumo(tabela,'OLD')}"
    else:
        raise ValueError('Operação de trigger inválida')
    return f'''CREATE OR ALTER TRIGGER TG_{sigla}_{tabela}_LOG FOR {tabela}
ACTIVE AFTER {operacao} POSITION 32000
AS
DECLARE VARIABLE V_DESTINO VARCHAR(512);
DECLARE VARIABLE V_USUARIO VARCHAR(63);
DECLARE VARIABLE V_SENHA VARCHAR(255);
BEGIN
    SELECT DATA_SOURCE, USUARIO, SENHA FROM CONFIGURACAO_LOG
    WHERE ID_CONFIGURACAO = 1 INTO :V_DESTINO, :V_USUARIO, :V_SENHA;
    IF (V_DESTINO IS NULL) THEN EXCEPTION EX_LOG_CONFIGURACAO;

    EXECUTE STATEMENT (
        'INSERT INTO LOG (DATA_HORA, USUARIO, TABELA, ID_REGISTRO, ACAO, VALOR_ANTERIOR, VALOR_NOVO)
         VALUES (CURRENT_TIMESTAMP, :usuario, ''{tabela}'', :registro, ''{operacao}'', {valores})'
    ) (
        usuario := COALESCE(RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_USUARIO_LOG'), RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_ID_USUARIO'), CURRENT_USER),
        registro := {registro}.{chave},
        {parametros}
    )
    ON EXTERNAL DATA SOURCE :V_DESTINO
    AS USER :V_USUARIO PASSWORD :V_SENHA
    WITH COMMON TRANSACTION;
END^
'''


def main():
    sql = ['SET BAIL ON;','SET AUTODDL OFF;','SET TERM ^;']
    sql.extend(f'DROP TRIGGER TG_AIUD_{tabela}_LOG^' for tabela in TABELAS_PRINCIPAIS)
    for tabela in TABELAS_PRINCIPAIS:
        for _,operacao,_ in OPERACOES:
            sql.append(gerar_trigger(tabela,operacao))
    sql.extend(['SET TERM ;^','COMMIT;'])
    caminho = ROOT/'migrations/016_log_tres_triggers.sql'
    caminho.write_text('\n'.join(sql),encoding='utf-8')
    print(caminho)


if __name__ == '__main__':
    main()
