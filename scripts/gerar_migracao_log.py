"""Gera o DDL explícito de log a partir do schema online conferido em 26/10/2026.

Não conecta em banco. O SQL gerado é revisado e aplicado em uma transação separada.
"""
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / 'tests/fixtures/log_schema_online_20261026.json'

TABELAS_PRINCIPAIS = (
    'USUARIO', 'CONTA', 'MOVIMENTACAO', 'COBRANCA', 'CARTAO', 'CHAVE_PIX',
    'COMPRA', 'FATURA', 'AGENDAMENTO_FINANCEIRO', 'RECORRENCIA_FINANCEIRA',
    'ESTORNO_FINANCEIRO',
)

# Somente metadados da operação. Conteúdo de mensagens, dados pessoais,
# chaves Pix, códigos, PIN, CVV, senhas, tokens e hashes não são copiados.
CAMPOS = {
    'ACESSO_CONTA': 'ID_ACESSO ID_CONTA ID_USUARIO STATUS ID_CONCEDIDO_POR',
    'AGENDAMENTO_EXECUCAO': 'ID_AGENDAMENTO ID_MOVIMENTACAO EXECUTADO_EM',
    'AGENDAMENTO_FINANCEIRO': 'ID_AGENDAMENTO ID_USUARIO ID_CONTA ID_CONTA_DESTINO ID_COBRANCA VALOR DATA_AGENDADA STATUS TENTATIVAS',
    'AUDITORIA_LIMITE': 'ID_AUDITORIA EVENTO ID_ADMINISTRADOR ID_USUARIO ID_CONTA TIPO_CONTA OPERACAO PERIODO VALOR_SOLICITADO VALOR_ACUMULADO LIMITE_POR_OPERACAO LIMITE_ACUMULADO',
    'AUDITORIA_LIMITE_CARTAO': 'ID_AUDITORIA ID_ADMINISTRADOR ID_CARTAO ID_CONTA LIMITE_ANTERIOR LIMITE_NOVO',
    'CARTAO': 'ID_CARTAO ID_CONTA STATUS LIMITE TENTATIVAS_PIN DATA_BLOQUEIO',
    'CHAVE_PIX': 'ID_CHAVE_PIX ID_CONTA',
    'COBRANCA': 'ID_COBRANCA ID_PAGADOR ID_RECEBEDOR VALOR DATA_VENCIMENTO STATUS TIPO_COBRANCA',
    'COMPRA': 'ID_COMPRA ID_CARTAO VALOR_COMPRA TIPO VALOR_PARCELA QTD_PARCELA DATA_COMPRA',
    'CONTA': 'ID_CONTA ID_USUARIO TIPO_CONTA WHATSAPP_AUTORIZADO WHATSAPP_NIVEL',
    'ESTORNO_FINANCEIRO': 'ID_ESTORNO ID_COBRANCA ID_MOVIMENTACAO_ORIGINAL ID_MOVIMENTACAO_REVERSA ID_CONTA_SOLICITANTE ID_USUARIO_RESPONSAVEL ID_CONTA_PAGADOR ID_CONTA_RECEBEDOR VALOR STATUS',
    'FATURA': 'ID_FATURA ID_CONTA VALOR_TOTAL STATUS DATA_FECHAMENTO DATA_VENCIMENTO',
    'FATURA_COMPRA': 'ID_FATURA_COMPRA ID_COMPRA ID_FATURA NUMERO_PARCELA STATUS VALOR_PARCELA DATA_PARCELA',
    'FAVORITO_PIX': 'ID_FAVORITO ID_CONTA ID_USUARIO ID_CONTA_DESTINO ATIVO',
    'FOLHA_ITEM': 'ID_FOLHA_ITEM ID_FOLHA ID_FUNCIONARIO ID_CONTA_DESTINO ID_MOVIMENTACAO VALOR STATUS DATA_PAGAMENTO',
    'FOLHA_PAGAMENTO': 'ID_FOLHA ID_CONTA_EMPRESA COMPETENCIA_MES COMPETENCIA_ANO STATUS DATA_CRIACAO DATA_PAGAMENTO',
    'FUNCIONARIO': 'ID_FUNCIONARIO ID_CONTA_EMPRESA ID_USUARIO SALARIO STATUS',
    'INTEGRACAO_API': 'ID_INTEGRACAO ID_CONTA ATIVO ULTIMO_USO',
    'LIMITE_CONTA_OPERACAO': 'ID_CONTA OPERACAO PERIODO LIMITE_POR_OPERACAO LIMITE_POR_OPERACAO_FAVORITO ATUALIZADO_POR',
    'LIMITE_CONTA_PERIODO': 'ID_CONTA PERIODO LIMITE_ACUMULADO ATUALIZADO_POR',
    'MAURO_CONVERSA': 'ID_CONVERSA ID_USUARIO ID_CONTA CRIADA_EM ATUALIZADA_EM',
    'MAURO_MENSAGEM': 'ID_MENSAGEM ID_CONVERSA PAPEL CRIADA_EM',
    'MAURO_PIX_PIN_TENTATIVA': 'ID_TENTATIVA ID_USUARIO ID_CONTA ID_PROPOSTA RESULTADO TENTATIVA_EM',
    'MAURO_PIX_PROPOSTA': 'ID_PROPOSTA ID_CONVERSA ID_USUARIO ID_CONTA_ORIGEM ID_CONTA_DESTINO VALOR STATUS EXPIRA_EM ID_MOVIMENTACAO',
    'MOVIMENTACAO': 'ID_MOVIMENTACAO ID_PAGADOR ID_RECEBEDOR VALOR DATA_MOVIMENTACAO ID_COBRANCA ID_COMPRA',
    'NOTIFICACAO': 'ID_NOTIFICACAO ID_EVENTO ID_CONTA ID_USUARIO_DESTINO CATEGORIA CRIADO_EM',
    'NOTIFICACAO_DESTINATARIO': 'ID_DESTINATARIO ID_NOTIFICACAO ID_USUARIO ID_CONTA LIDA_EM SUPRIMIDA_EM',
    'POLITICA_LIMITE_OPERACAO': 'TIPO_CONTA OPERACAO PERIODO ATIVO LIMITE_POR_OPERACAO LIMITE_POR_OPERACAO_FAVORITO ATUALIZADO_POR',
    'POLITICA_LIMITE_PERIODO': 'TIPO_CONTA PERIODO ATIVO LIMITE_ACUMULADO ATUALIZADO_POR',
    'PREFERENCIA_NOTIFICACAO': 'ID_USUARIO CATEGORIA ATIVO',
    'RECORRENCIA_EXECUCAO': 'ID_REC_EXECUCAO ID_RECORRENCIA NUMERO_EXECUCAO ID_AGENDAMENTO DATA_PREVISTA STATUS',
    'RECORRENCIA_FINANCEIRA': 'ID_RECORRENCIA ID_USUARIO ID_CONTA ID_CONTA_DESTINO ID_COBRANCA VALOR FREQUENCIA DATA_INICIAL DATA_FINAL LIMITE_EXECUCOES EXECUCOES_CRIADAS PROXIMA_EXECUCAO STATUS',
    'RECUPERACAO_SENHA': 'ID_RECUPERACAO_SENHA ID_USUARIO EXPIRA_EM UTILIZADO_EM',
    'USUARIO': 'ID_USUARIO TIPO STATUS TENTATIVAS PRIMEIRO_ACESSO',
    'VERIFICACAO_PIX': 'ID_VERIFICACAO ID_CONTA TENTATIVAS STATUS EXPIRA_EM CONFIRMADO_EM',
}


def texto_sql(texto):
    return "'" + texto.replace("'", "''") + "'"


def snapshot(tabela, registro, campos_schema):
    partes = []
    for campo in CAMPOS[tabela].split():
        tipo = campos_schema[tabela, campo][2]
        valor = f'CAST({registro}.{campo} AS VARCHAR(80))'
        if tipo in (14, 37):
            # Escapa aspas e barras também para alterações feitas por SQL manual.
            valor = f"REPLACE(REPLACE({valor}, ASCII_CHAR(92), ASCII_CHAR(92) || ASCII_CHAR(92)), ASCII_CHAR(34), ASCII_CHAR(92) || ASCII_CHAR(34))"
            for codigo, escape in ((13, 'r'), (10, 'n'), (9, 't')):
                valor = f"REPLACE({valor}, ASCII_CHAR({codigo}), ASCII_CHAR(92) || '{escape}')"
        if tipo in (12, 13, 14, 35, 37):
            valor = f"'\"' || {valor} || '\"'"
        partes.append(texto_sql(('{' if not partes else ',') + '"' + campo.lower() + '":') + f" || COALESCE({valor}, 'null')")
    if tabela == 'MAURO_MENSAGEM':
        partes.append(f"',\"caracteres\":' || CAST(CHAR_LENGTH({registro}.CONTEUDO) AS VARCHAR(12))")
    return (' ||\n                    '.join(partes)) + " || '}'"


def parametros(tabela, operacao):
    r = 'OLD' if operacao == 'DELETE' else 'NEW'
    campos = CAMPOS[tabela].split()
    conta = next((f'{r}.{c}' for c in ('ID_CONTA', 'ID_CONTA_ORIGEM', 'ID_CONTA_EMPRESA', 'ID_PAGADOR', 'ID_CONTA_SOLICITANTE') if c in campos), 'NULL')
    usuario = "CAST(RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_ID_USUARIO') AS INTEGER)"
    valor = next((f'{r}.{c}' for c in ('VALOR', 'VALOR_COMPRA', 'VALOR_PARCELA', 'VALOR_TOTAL', 'VALOR_SOLICITADO', 'LIMITE_NOVO', 'SALARIO') if c in campos), 'NULL')
    evento = texto_sql(tabela)
    resultado = texto_sql({'INSERT': 'REGISTRADO', 'UPDATE': 'ATUALIZADO', 'DELETE': 'EXCLUIDO'}[operacao])
    if tabela == 'MOVIMENTACAO' and operacao == 'INSERT':
        resultado = "'CONCLUIDO'"
    if tabela == 'COBRANCA' and operacao != 'DELETE':
        conta = f'COALESCE({r}.ID_PAGADOR, {r}.ID_RECEBEDOR)'
        resultado = f"CASE {r}.STATUS WHEN 1 THEN 'CONCLUIDO' WHEN 2 THEN 'CANCELADO' ELSE 'PENDENTE' END"
    if tabela == 'AUDITORIA_LIMITE':
        usuario = f'COALESCE({usuario}, {r}.ID_ADMINISTRADOR, {r}.ID_USUARIO)'
        if operacao == 'INSERT':
            evento = "CASE NEW.EVENTO WHEN 'OPERACAO_RECUSADA' THEN 'OPERACAO_RECUSADA_LIMITE' ELSE 'LIMITE_POLITICA_ALTERADA' END"
            resultado = "CASE NEW.EVENTO WHEN 'OPERACAO_RECUSADA' THEN 'RECUSADO' ELSE 'SUCESSO' END"
    if tabela == 'AUDITORIA_LIMITE_CARTAO':
        usuario = f'COALESCE({usuario}, {r}.ID_ADMINISTRADOR)'
    if tabela == 'CARTAO':
        if operacao == 'INSERT':
            evento, resultado = "'CARTAO_CRIADO'", "'CRIADO'"
        elif operacao == 'UPDATE':
            evento = "CASE WHEN OLD.STATUS IS DISTINCT FROM NEW.STATUS THEN 'CARTAO_STATUS_ALTERADO' WHEN OLD.LIMITE IS DISTINCT FROM NEW.LIMITE THEN 'CARTAO_LIMITE_ALTERADO' ELSE 'CARTAO_ALTERADO' END"
            resultado = "CASE WHEN NEW.STATUS = 1 THEN 'BLOQUEADO' ELSE 'ATUALIZADO' END"
    if tabela == 'USUARIO' and operacao == 'UPDATE':
        evento = "CASE WHEN OLD.STATUS IS DISTINCT FROM NEW.STATUS THEN 'USUARIO_STATUS' ELSE 'USUARIO_ALTERADO' END"
    if tabela == 'ESTORNO_FINANCEIRO':
        evento = f'{r}.TIPO_OPERACAO'
        if operacao != 'DELETE':
            resultado = f'{r}.STATUS'
    if tabela in ('COMPRA', 'FATURA_COMPRA'):
        compra = f'{r}.ID_COMPRA'
        conta = f'(SELECT C.ID_CONTA FROM CARTAO C JOIN COMPRA CP ON CP.ID_CARTAO = C.ID_CARTAO WHERE CP.ID_COMPRA = {compra})'
        if tabela == 'COMPRA':
            conta = f'(SELECT C.ID_CONTA FROM CARTAO C WHERE C.ID_CARTAO = {r}.ID_CARTAO)'
    if tabela == 'MAURO_MENSAGEM':
        conta = f'(SELECT C.ID_CONTA FROM MAURO_CONVERSA C WHERE C.ID_CONVERSA = {r}.ID_CONVERSA)'
        usuario = f'COALESCE({usuario}, (SELECT C.ID_USUARIO FROM MAURO_CONVERSA C WHERE C.ID_CONVERSA = {r}.ID_CONVERSA))'
    registro = 'NULL' if tabela.startswith('POLITICA_LIMITE_') else f'{r}.{campos[0]}'
    return evento, registro, usuario, conta, valor, resultado


def gerar_trigger(tabela, operacao, campos_schema):
    sigla = {'INSERT': 'AI', 'UPDATE': 'AU', 'DELETE': 'AD'}[operacao]
    evento, registro, usuario, conta, valor, resultado = parametros(tabela, operacao)
    anterior = snapshot(tabela, 'OLD', campos_schema) if operacao != 'INSERT' else 'NULL'
    novo = snapshot(tabela, 'NEW', campos_schema) if operacao != 'DELETE' else 'NULL'
    return f'''CREATE OR ALTER TRIGGER TG_{sigla}_{tabela}_LOG FOR {tabela}
ACTIVE AFTER {operacao} POSITION 32000
AS
DECLARE VARIABLE V_DESTINO VARCHAR(512);
DECLARE VARIABLE V_USUARIO VARCHAR(63);
DECLARE VARIABLE V_SENHA VARCHAR(255);
DECLARE VARIABLE V_ORIGEM_ID VARCHAR(80);
BEGIN
    SELECT DATA_SOURCE, USUARIO, SENHA, ORIGEM_ID
    FROM CONFIGURACAO_LOG WHERE ID_CONFIGURACAO = 1
    INTO :V_DESTINO, :V_USUARIO, :V_SENHA, :V_ORIGEM_ID;
    IF (V_DESTINO IS NULL) THEN
        EXCEPTION EX_LOG_CONFIGURACAO;

    EXECUTE STATEMENT (
        'INSERT INTO AUDITORIA_EVENTO (
            ORIGEM_ID, ID_EVENTO_ORIGEM, EVENTO, TABELA_ORIGEM, OPERACAO,
            ID_REGISTRO, ID_USUARIO, ID_CONTA, VALOR, RESULTADO,
            ORIGEM, DADOS_ANTERIORES, DADOS_NOVOS, CRIADO_EM
        ) VALUES (
            :origem_id, :id_evento, :evento, ''{tabela}'', ''{operacao}'',
            :id_registro, :id_usuario, :id_conta, :valor, :resultado,
            :origem, :antes, :depois, :criado_em
        )'
    ) (
        origem_id := :V_ORIGEM_ID,
        id_evento := NEXT VALUE FOR GEN_LOG_EVENTO,
        evento := {evento},
        id_registro := {registro},
        id_usuario := {usuario},
        id_conta := {conta},
        valor := {valor},
        resultado := {resultado},
        origem := COALESCE(RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_ORIGEM'), 'SQL:' || CURRENT_USER),
        antes := {anterior},
        depois := {novo},
        criado_em := CURRENT_TIMESTAMP
    )
    ON EXTERNAL DATA SOURCE :V_DESTINO
    AS USER :V_USUARIO
    PASSWORD :V_SENHA
    WITH COMMON TRANSACTION;
END^
'''


def gerar_trigger_unica(tabela, campos_schema):
    insercao = parametros(tabela, 'INSERT')
    alteracao = parametros(tabela, 'UPDATE')
    exclusao = parametros(tabela, 'DELETE')
    valores = []
    for i, u, d in zip(insercao, alteracao, exclusao):
        if i == u == d:
            valores.append(i)
        elif i == u:
            valores.append(f'CASE WHEN DELETING THEN {d} ELSE {i} END')
        else:
            valores.append(f'CASE WHEN INSERTING THEN {i} WHEN UPDATING THEN {u} ELSE {d} END')
    evento, registro, usuario, conta, valor, resultado = valores
    return f'''CREATE OR ALTER TRIGGER TG_AIUD_{tabela}_LOG FOR {tabela}
ACTIVE AFTER INSERT OR UPDATE OR DELETE POSITION 32000
AS
DECLARE VARIABLE V_DESTINO VARCHAR(512);
DECLARE VARIABLE V_USUARIO VARCHAR(63);
DECLARE VARIABLE V_SENHA VARCHAR(255);
DECLARE VARIABLE V_ORIGEM_ID VARCHAR(80);
BEGIN
    SELECT DATA_SOURCE, USUARIO, SENHA, ORIGEM_ID
    FROM CONFIGURACAO_LOG WHERE ID_CONFIGURACAO = 1
    INTO :V_DESTINO, :V_USUARIO, :V_SENHA, :V_ORIGEM_ID;
    IF (V_DESTINO IS NULL) THEN
        EXCEPTION EX_LOG_CONFIGURACAO;

    EXECUTE STATEMENT (
        'INSERT INTO AUDITORIA_EVENTO (
            ORIGEM_ID, ID_EVENTO_ORIGEM, EVENTO, TABELA_ORIGEM, OPERACAO,
            ID_REGISTRO, ID_USUARIO, ID_CONTA, VALOR, RESULTADO,
            ORIGEM, DADOS_ANTERIORES, DADOS_NOVOS, CRIADO_EM
        ) VALUES (
            :origem_id, :id_evento, :evento, ''{tabela}'', :operacao,
            :id_registro, :id_usuario, :id_conta, :valor, :resultado,
            :origem, :antes, :depois, :criado_em
        )'
    ) (
        origem_id := :V_ORIGEM_ID,
        id_evento := NEXT VALUE FOR GEN_LOG_EVENTO,
        evento := TRIM({evento}),
        operacao := CASE WHEN INSERTING THEN 'INSERT' WHEN UPDATING THEN 'UPDATE' ELSE 'DELETE' END,
        id_registro := {registro},
        id_usuario := {usuario},
        id_conta := {conta},
        valor := {valor},
        resultado := TRIM({resultado}),
        origem := COALESCE(RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_ORIGEM'), 'SQL:' || CURRENT_USER),
        antes := CASE WHEN INSERTING THEN NULL ELSE {snapshot(tabela, 'OLD', campos_schema)} END,
        depois := CASE WHEN DELETING THEN NULL ELSE {snapshot(tabela, 'NEW', campos_schema)} END,
        criado_em := CURRENT_TIMESTAMP
    )
    ON EXTERNAL DATA SOURCE :V_DESTINO
    AS USER :V_USUARIO
    PASSWORD :V_SENHA
    WITH COMMON TRANSACTION;
END^
'''


def main():
    schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
    campos = {(r[0], r[1]): r for r in schema['fields']}
    sql = ['/* Uma trigger de LOG por tabela. Publicar o Python antes da troca. */',
           'SET BAIL ON;', 'SET AUTODDL OFF;', 'SET TERM ^;']
    for tabela in TABELAS_PRINCIPAIS:
        sql.append(gerar_trigger_unica(tabela, campos))
        nome = f'TG_AIUD_{tabela}_LOG'
        sql.append(f'GRANT SELECT ON CONFIGURACAO_LOG TO TRIGGER {nome}^')
        sql.append(f'GRANT USAGE ON SEQUENCE GEN_LOG_EVENTO TO TRIGGER {nome}^')
        if tabela == 'COMPRA':
            sql.append(f'GRANT SELECT ON CARTAO TO TRIGGER {nome}^')
    for tabela in TABELAS_PRINCIPAIS:
        for sigla in ('AI', 'AU', 'AD'):
            sql.append(f'DROP TRIGGER TG_{sigla}_{tabela}_LOG^')
    sql.extend(['SET TERM ;^', 'COMMIT;'])
    caminho = ROOT / 'migrations/013_log_uma_trigger_por_tabela.sql'
    caminho.write_text('\n'.join(sql) + '\n', encoding='utf-8')
    print(f'{len(TABELAS_PRINCIPAIS)} triggers de log: {caminho}')


if __name__ == '__main__':
    main()
