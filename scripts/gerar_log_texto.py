"""Uma trigger por tabela, com resumos em texto e uma gravação externa."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.gerar_migracao_log import CAMPOS,TABELAS_PRINCIPAIS


def resumo(tabela,registro):
    partes = []
    for campo in CAMPOS[tabela].split()[1:]:
        separador = '; ' if partes else ''
        partes.append(f"'{separador}{campo}=' || COALESCE(CAST({registro}.{campo} AS VARCHAR(80)), 'NULL')")
    return '\n            || '.join(partes)


def gerar_trigger(tabela):
    chave = CAMPOS[tabela].split()[0]
    return f'''CREATE OR ALTER TRIGGER TG_AIUD_{tabela}_LOG FOR {tabela}
ACTIVE AFTER INSERT OR UPDATE OR DELETE POSITION 32000
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
         VALUES (CURRENT_TIMESTAMP, :usuario, ''{tabela}'', :registro, :acao, :antes, :novo)'
    ) (
        usuario := COALESCE(RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_USUARIO_LOG'), RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_ID_USUARIO'), CURRENT_USER),
        registro := CASE WHEN DELETING THEN OLD.{chave} ELSE NEW.{chave} END,
        acao := CASE WHEN INSERTING THEN 'INSERT' WHEN UPDATING THEN 'UPDATE' ELSE 'DELETE' END,
        antes := CASE WHEN INSERTING THEN NULL ELSE
            {resumo(tabela,'OLD')} END,
        novo := CASE WHEN DELETING THEN NULL ELSE
            {resumo(tabela,'NEW')} END
    )
    ON EXTERNAL DATA SOURCE :V_DESTINO
    AS USER :V_USUARIO PASSWORD :V_SENHA
    WITH COMMON TRANSACTION;
END^
'''


def main():
    sql = ['SET BAIL ON;','SET AUTODDL OFF;','SET TERM ^;']
    sql.extend(gerar_trigger(tabela) for tabela in TABELAS_PRINCIPAIS)
    sql.extend(['SET TERM ;^','COMMIT;'])
    caminho = ROOT/'migrations/015_log_texto_simples.sql'
    caminho.write_text('\n'.join(sql),encoding='utf-8')
    print(caminho)


if __name__ == '__main__':
    main()
