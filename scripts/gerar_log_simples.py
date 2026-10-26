"""Gera uma trigger por tabela para a LOG de oito campos. Não conecta em banco."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.gerar_migracao_log import CAMPOS, SCHEMA, TABELAS_PRINCIPAIS, snapshot


def valor_json(registro, campo, tipo):
    valor = f'CAST({registro}.{campo} AS VARCHAR(80))'
    if tipo in (14,37):
        valor = f'REPLACE(REPLACE({valor}, ASCII_CHAR(92), ASCII_CHAR(92) || ASCII_CHAR(92)), ASCII_CHAR(34), ASCII_CHAR(92) || ASCII_CHAR(34))'
        for codigo, escape in ((13,'r'),(10,'n'),(9,'t')):
            valor = f"REPLACE({valor}, ASCII_CHAR({codigo}), ASCII_CHAR(92) || '{escape}')"
    if tipo in (12,13,14,35,37):
        valor = f"'\"' || {valor} || '\"'"
    return f"COALESCE({valor}, 'null')"


def gerar_trigger(tabela, campos):
    alteracoes = []
    for campo in CAMPOS[tabela].split():
        tipo = campos[tabela,campo][2]
        chave = '\"' + campo.lower() + '\":'
        alteracoes.append(f'''        IF (OLD.{campo} IS DISTINCT FROM NEW.{campo}) THEN
        BEGIN
            V_ANTES = V_ANTES || ',{chave}' || {valor_json('OLD',campo,tipo)};
            V_NOVO = V_NOVO || ',{chave}' || {valor_json('NEW',campo,tipo)};
        END''')
    chave = CAMPOS[tabela].split()[0]
    return f'''CREATE OR ALTER TRIGGER TG_AIUD_{tabela}_LOG FOR {tabela}
ACTIVE AFTER INSERT OR UPDATE OR DELETE POSITION 32000
AS
DECLARE VARIABLE V_DESTINO VARCHAR(512);
DECLARE VARIABLE V_USUARIO VARCHAR(63);
DECLARE VARIABLE V_SENHA VARCHAR(255);
DECLARE VARIABLE V_ANTES VARCHAR(4000);
DECLARE VARIABLE V_NOVO VARCHAR(4000);
BEGIN
    SELECT DATA_SOURCE, USUARIO, SENHA FROM CONFIGURACAO_LOG
    WHERE ID_CONFIGURACAO = 1 INTO :V_DESTINO, :V_USUARIO, :V_SENHA;
    IF (V_DESTINO IS NULL) THEN EXCEPTION EX_LOG_CONFIGURACAO;

    IF (INSERTING) THEN V_NOVO = {snapshot(tabela,'NEW',campos)};
    IF (DELETING) THEN V_ANTES = {snapshot(tabela,'OLD',campos)};
    IF (UPDATING) THEN
    BEGIN
        V_ANTES = '';
        V_NOVO = '';
{chr(10).join(alteracoes)}
        IF (V_ANTES <> '') THEN
        BEGIN
            V_ANTES = '{{' || SUBSTRING(V_ANTES FROM 2) || '}}';
            V_NOVO = '{{' || SUBSTRING(V_NOVO FROM 2) || '}}';
        END
        ELSE
        BEGIN
            V_ANTES = NULL;
            V_NOVO = NULL;
        END
    END

    EXECUTE STATEMENT (
        'INSERT INTO LOG (DATA_HORA, USUARIO, TABELA, ID_REGISTRO, ACAO, VALOR_ANTERIOR, VALOR_NOVO)
         VALUES (:data_hora, :usuario, ''{tabela}'', :id_registro, :acao, :antes, :novo)'
    ) (
        data_hora := CURRENT_TIMESTAMP,
        usuario := COALESCE(RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_USUARIO_LOG'), RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_ID_USUARIO'), CURRENT_USER),
        id_registro := CASE WHEN DELETING THEN OLD.{chave} ELSE NEW.{chave} END,
        acao := CASE WHEN INSERTING THEN 'INSERT' WHEN UPDATING THEN 'UPDATE' ELSE 'DELETE' END,
        antes := :V_ANTES,
        novo := :V_NOVO
    )
    ON EXTERNAL DATA SOURCE :V_DESTINO
    AS USER :V_USUARIO PASSWORD :V_SENHA
    WITH COMMON TRANSACTION;
END^
'''


def main():
    schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
    campos = {(r[0],r[1]):r for r in schema['fields']}
    sql = ['SET BAIL ON;', 'SET AUTODDL OFF;', 'SET TERM ^;']
    for tabela in TABELAS_PRINCIPAIS:
        sql.append(gerar_trigger(tabela,campos))
    sql.extend(['SET TERM ;^','COMMIT;'])
    caminho = ROOT/'migrations/014_log_oito_campos.sql'
    caminho.write_text('\n'.join(sql),encoding='utf-8')
    print(caminho)


if __name__ == '__main__':
    main()
