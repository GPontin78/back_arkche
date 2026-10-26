SET BAIL ON;
SET AUTODDL OFF;
SET TERM ^;
CREATE OR ALTER TRIGGER TG_AIUD_USUARIO_LOG FOR USUARIO
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

    IF (INSERTING) THEN V_NOVO = '{"id_usuario":' || COALESCE(CAST(NEW.ID_USUARIO AS VARCHAR(80)), 'null') ||
                    ',"tipo":' || COALESCE(CAST(NEW.TIPO AS VARCHAR(80)), 'null') ||
                    ',"status":' || COALESCE(CAST(NEW.STATUS AS VARCHAR(80)), 'null') ||
                    ',"tentativas":' || COALESCE(CAST(NEW.TENTATIVAS AS VARCHAR(80)), 'null') ||
                    ',"primeiro_acesso":' || COALESCE(CAST(NEW.PRIMEIRO_ACESSO AS VARCHAR(80)), 'null') || '}';
    IF (DELETING) THEN V_ANTES = '{"id_usuario":' || COALESCE(CAST(OLD.ID_USUARIO AS VARCHAR(80)), 'null') ||
                    ',"tipo":' || COALESCE(CAST(OLD.TIPO AS VARCHAR(80)), 'null') ||
                    ',"status":' || COALESCE(CAST(OLD.STATUS AS VARCHAR(80)), 'null') ||
                    ',"tentativas":' || COALESCE(CAST(OLD.TENTATIVAS AS VARCHAR(80)), 'null') ||
                    ',"primeiro_acesso":' || COALESCE(CAST(OLD.PRIMEIRO_ACESSO AS VARCHAR(80)), 'null') || '}';
    IF (UPDATING) THEN
    BEGIN
        V_ANTES = '';
        V_NOVO = '';
        IF (OLD.ID_USUARIO IS DISTINCT FROM NEW.ID_USUARIO) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_usuario":' || COALESCE(CAST(OLD.ID_USUARIO AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_usuario":' || COALESCE(CAST(NEW.ID_USUARIO AS VARCHAR(80)), 'null');
        END
        IF (OLD.TIPO IS DISTINCT FROM NEW.TIPO) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"tipo":' || COALESCE(CAST(OLD.TIPO AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"tipo":' || COALESCE(CAST(NEW.TIPO AS VARCHAR(80)), 'null');
        END
        IF (OLD.STATUS IS DISTINCT FROM NEW.STATUS) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"status":' || COALESCE(CAST(OLD.STATUS AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"status":' || COALESCE(CAST(NEW.STATUS AS VARCHAR(80)), 'null');
        END
        IF (OLD.TENTATIVAS IS DISTINCT FROM NEW.TENTATIVAS) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"tentativas":' || COALESCE(CAST(OLD.TENTATIVAS AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"tentativas":' || COALESCE(CAST(NEW.TENTATIVAS AS VARCHAR(80)), 'null');
        END
        IF (OLD.PRIMEIRO_ACESSO IS DISTINCT FROM NEW.PRIMEIRO_ACESSO) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"primeiro_acesso":' || COALESCE(CAST(OLD.PRIMEIRO_ACESSO AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"primeiro_acesso":' || COALESCE(CAST(NEW.PRIMEIRO_ACESSO AS VARCHAR(80)), 'null');
        END
        IF (V_ANTES <> '') THEN
        BEGIN
            V_ANTES = '{' || SUBSTRING(V_ANTES FROM 2) || '}';
            V_NOVO = '{' || SUBSTRING(V_NOVO FROM 2) || '}';
        END
        ELSE
        BEGIN
            V_ANTES = NULL;
            V_NOVO = NULL;
        END
    END

    EXECUTE STATEMENT (
        'INSERT INTO LOG (DATA_HORA, USUARIO, TABELA, ID_REGISTRO, ACAO, VALOR_ANTERIOR, VALOR_NOVO)
         VALUES (:data_hora, :usuario, ''USUARIO'', :id_registro, :acao, :antes, :novo)'
    ) (
        data_hora := CURRENT_TIMESTAMP,
        usuario := COALESCE(RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_USUARIO_LOG'), RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_ID_USUARIO'), CURRENT_USER),
        id_registro := CASE WHEN DELETING THEN OLD.ID_USUARIO ELSE NEW.ID_USUARIO END,
        acao := CASE WHEN INSERTING THEN 'INSERT' WHEN UPDATING THEN 'UPDATE' ELSE 'DELETE' END,
        antes := :V_ANTES,
        novo := :V_NOVO
    )
    ON EXTERNAL DATA SOURCE :V_DESTINO
    AS USER :V_USUARIO PASSWORD :V_SENHA
    WITH COMMON TRANSACTION;
END^

CREATE OR ALTER TRIGGER TG_AIUD_CONTA_LOG FOR CONTA
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

    IF (INSERTING) THEN V_NOVO = '{"id_conta":' || COALESCE(CAST(NEW.ID_CONTA AS VARCHAR(80)), 'null') ||
                    ',"id_usuario":' || COALESCE(CAST(NEW.ID_USUARIO AS VARCHAR(80)), 'null') ||
                    ',"tipo_conta":' || COALESCE(CAST(NEW.TIPO_CONTA AS VARCHAR(80)), 'null') ||
                    ',"whatsapp_autorizado":' || COALESCE(CAST(NEW.WHATSAPP_AUTORIZADO AS VARCHAR(80)), 'null') ||
                    ',"whatsapp_nivel":' || COALESCE(CAST(NEW.WHATSAPP_NIVEL AS VARCHAR(80)), 'null') || '}';
    IF (DELETING) THEN V_ANTES = '{"id_conta":' || COALESCE(CAST(OLD.ID_CONTA AS VARCHAR(80)), 'null') ||
                    ',"id_usuario":' || COALESCE(CAST(OLD.ID_USUARIO AS VARCHAR(80)), 'null') ||
                    ',"tipo_conta":' || COALESCE(CAST(OLD.TIPO_CONTA AS VARCHAR(80)), 'null') ||
                    ',"whatsapp_autorizado":' || COALESCE(CAST(OLD.WHATSAPP_AUTORIZADO AS VARCHAR(80)), 'null') ||
                    ',"whatsapp_nivel":' || COALESCE(CAST(OLD.WHATSAPP_NIVEL AS VARCHAR(80)), 'null') || '}';
    IF (UPDATING) THEN
    BEGIN
        V_ANTES = '';
        V_NOVO = '';
        IF (OLD.ID_CONTA IS DISTINCT FROM NEW.ID_CONTA) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_conta":' || COALESCE(CAST(OLD.ID_CONTA AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_conta":' || COALESCE(CAST(NEW.ID_CONTA AS VARCHAR(80)), 'null');
        END
        IF (OLD.ID_USUARIO IS DISTINCT FROM NEW.ID_USUARIO) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_usuario":' || COALESCE(CAST(OLD.ID_USUARIO AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_usuario":' || COALESCE(CAST(NEW.ID_USUARIO AS VARCHAR(80)), 'null');
        END
        IF (OLD.TIPO_CONTA IS DISTINCT FROM NEW.TIPO_CONTA) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"tipo_conta":' || COALESCE(CAST(OLD.TIPO_CONTA AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"tipo_conta":' || COALESCE(CAST(NEW.TIPO_CONTA AS VARCHAR(80)), 'null');
        END
        IF (OLD.WHATSAPP_AUTORIZADO IS DISTINCT FROM NEW.WHATSAPP_AUTORIZADO) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"whatsapp_autorizado":' || COALESCE(CAST(OLD.WHATSAPP_AUTORIZADO AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"whatsapp_autorizado":' || COALESCE(CAST(NEW.WHATSAPP_AUTORIZADO AS VARCHAR(80)), 'null');
        END
        IF (OLD.WHATSAPP_NIVEL IS DISTINCT FROM NEW.WHATSAPP_NIVEL) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"whatsapp_nivel":' || COALESCE(CAST(OLD.WHATSAPP_NIVEL AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"whatsapp_nivel":' || COALESCE(CAST(NEW.WHATSAPP_NIVEL AS VARCHAR(80)), 'null');
        END
        IF (V_ANTES <> '') THEN
        BEGIN
            V_ANTES = '{' || SUBSTRING(V_ANTES FROM 2) || '}';
            V_NOVO = '{' || SUBSTRING(V_NOVO FROM 2) || '}';
        END
        ELSE
        BEGIN
            V_ANTES = NULL;
            V_NOVO = NULL;
        END
    END

    EXECUTE STATEMENT (
        'INSERT INTO LOG (DATA_HORA, USUARIO, TABELA, ID_REGISTRO, ACAO, VALOR_ANTERIOR, VALOR_NOVO)
         VALUES (:data_hora, :usuario, ''CONTA'', :id_registro, :acao, :antes, :novo)'
    ) (
        data_hora := CURRENT_TIMESTAMP,
        usuario := COALESCE(RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_USUARIO_LOG'), RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_ID_USUARIO'), CURRENT_USER),
        id_registro := CASE WHEN DELETING THEN OLD.ID_CONTA ELSE NEW.ID_CONTA END,
        acao := CASE WHEN INSERTING THEN 'INSERT' WHEN UPDATING THEN 'UPDATE' ELSE 'DELETE' END,
        antes := :V_ANTES,
        novo := :V_NOVO
    )
    ON EXTERNAL DATA SOURCE :V_DESTINO
    AS USER :V_USUARIO PASSWORD :V_SENHA
    WITH COMMON TRANSACTION;
END^

CREATE OR ALTER TRIGGER TG_AIUD_MOVIMENTACAO_LOG FOR MOVIMENTACAO
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

    IF (INSERTING) THEN V_NOVO = '{"id_movimentacao":' || COALESCE(CAST(NEW.ID_MOVIMENTACAO AS VARCHAR(80)), 'null') ||
                    ',"id_pagador":' || COALESCE(CAST(NEW.ID_PAGADOR AS VARCHAR(80)), 'null') ||
                    ',"id_recebedor":' || COALESCE(CAST(NEW.ID_RECEBEDOR AS VARCHAR(80)), 'null') ||
                    ',"valor":' || COALESCE(CAST(NEW.VALOR AS VARCHAR(80)), 'null') ||
                    ',"data_movimentacao":' || COALESCE('"' || CAST(NEW.DATA_MOVIMENTACAO AS VARCHAR(80)) || '"', 'null') ||
                    ',"id_cobranca":' || COALESCE(CAST(NEW.ID_COBRANCA AS VARCHAR(80)), 'null') ||
                    ',"id_compra":' || COALESCE(CAST(NEW.ID_COMPRA AS VARCHAR(80)), 'null') || '}';
    IF (DELETING) THEN V_ANTES = '{"id_movimentacao":' || COALESCE(CAST(OLD.ID_MOVIMENTACAO AS VARCHAR(80)), 'null') ||
                    ',"id_pagador":' || COALESCE(CAST(OLD.ID_PAGADOR AS VARCHAR(80)), 'null') ||
                    ',"id_recebedor":' || COALESCE(CAST(OLD.ID_RECEBEDOR AS VARCHAR(80)), 'null') ||
                    ',"valor":' || COALESCE(CAST(OLD.VALOR AS VARCHAR(80)), 'null') ||
                    ',"data_movimentacao":' || COALESCE('"' || CAST(OLD.DATA_MOVIMENTACAO AS VARCHAR(80)) || '"', 'null') ||
                    ',"id_cobranca":' || COALESCE(CAST(OLD.ID_COBRANCA AS VARCHAR(80)), 'null') ||
                    ',"id_compra":' || COALESCE(CAST(OLD.ID_COMPRA AS VARCHAR(80)), 'null') || '}';
    IF (UPDATING) THEN
    BEGIN
        V_ANTES = '';
        V_NOVO = '';
        IF (OLD.ID_MOVIMENTACAO IS DISTINCT FROM NEW.ID_MOVIMENTACAO) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_movimentacao":' || COALESCE(CAST(OLD.ID_MOVIMENTACAO AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_movimentacao":' || COALESCE(CAST(NEW.ID_MOVIMENTACAO AS VARCHAR(80)), 'null');
        END
        IF (OLD.ID_PAGADOR IS DISTINCT FROM NEW.ID_PAGADOR) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_pagador":' || COALESCE(CAST(OLD.ID_PAGADOR AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_pagador":' || COALESCE(CAST(NEW.ID_PAGADOR AS VARCHAR(80)), 'null');
        END
        IF (OLD.ID_RECEBEDOR IS DISTINCT FROM NEW.ID_RECEBEDOR) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_recebedor":' || COALESCE(CAST(OLD.ID_RECEBEDOR AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_recebedor":' || COALESCE(CAST(NEW.ID_RECEBEDOR AS VARCHAR(80)), 'null');
        END
        IF (OLD.VALOR IS DISTINCT FROM NEW.VALOR) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"valor":' || COALESCE(CAST(OLD.VALOR AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"valor":' || COALESCE(CAST(NEW.VALOR AS VARCHAR(80)), 'null');
        END
        IF (OLD.DATA_MOVIMENTACAO IS DISTINCT FROM NEW.DATA_MOVIMENTACAO) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"data_movimentacao":' || COALESCE('"' || CAST(OLD.DATA_MOVIMENTACAO AS VARCHAR(80)) || '"', 'null');
            V_NOVO = V_NOVO || ',"data_movimentacao":' || COALESCE('"' || CAST(NEW.DATA_MOVIMENTACAO AS VARCHAR(80)) || '"', 'null');
        END
        IF (OLD.ID_COBRANCA IS DISTINCT FROM NEW.ID_COBRANCA) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_cobranca":' || COALESCE(CAST(OLD.ID_COBRANCA AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_cobranca":' || COALESCE(CAST(NEW.ID_COBRANCA AS VARCHAR(80)), 'null');
        END
        IF (OLD.ID_COMPRA IS DISTINCT FROM NEW.ID_COMPRA) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_compra":' || COALESCE(CAST(OLD.ID_COMPRA AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_compra":' || COALESCE(CAST(NEW.ID_COMPRA AS VARCHAR(80)), 'null');
        END
        IF (V_ANTES <> '') THEN
        BEGIN
            V_ANTES = '{' || SUBSTRING(V_ANTES FROM 2) || '}';
            V_NOVO = '{' || SUBSTRING(V_NOVO FROM 2) || '}';
        END
        ELSE
        BEGIN
            V_ANTES = NULL;
            V_NOVO = NULL;
        END
    END

    EXECUTE STATEMENT (
        'INSERT INTO LOG (DATA_HORA, USUARIO, TABELA, ID_REGISTRO, ACAO, VALOR_ANTERIOR, VALOR_NOVO)
         VALUES (:data_hora, :usuario, ''MOVIMENTACAO'', :id_registro, :acao, :antes, :novo)'
    ) (
        data_hora := CURRENT_TIMESTAMP,
        usuario := COALESCE(RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_USUARIO_LOG'), RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_ID_USUARIO'), CURRENT_USER),
        id_registro := CASE WHEN DELETING THEN OLD.ID_MOVIMENTACAO ELSE NEW.ID_MOVIMENTACAO END,
        acao := CASE WHEN INSERTING THEN 'INSERT' WHEN UPDATING THEN 'UPDATE' ELSE 'DELETE' END,
        antes := :V_ANTES,
        novo := :V_NOVO
    )
    ON EXTERNAL DATA SOURCE :V_DESTINO
    AS USER :V_USUARIO PASSWORD :V_SENHA
    WITH COMMON TRANSACTION;
END^

CREATE OR ALTER TRIGGER TG_AIUD_COBRANCA_LOG FOR COBRANCA
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

    IF (INSERTING) THEN V_NOVO = '{"id_cobranca":' || COALESCE(CAST(NEW.ID_COBRANCA AS VARCHAR(80)), 'null') ||
                    ',"id_pagador":' || COALESCE(CAST(NEW.ID_PAGADOR AS VARCHAR(80)), 'null') ||
                    ',"id_recebedor":' || COALESCE(CAST(NEW.ID_RECEBEDOR AS VARCHAR(80)), 'null') ||
                    ',"valor":' || COALESCE(CAST(NEW.VALOR AS VARCHAR(80)), 'null') ||
                    ',"data_vencimento":' || COALESCE('"' || CAST(NEW.DATA_VENCIMENTO AS VARCHAR(80)) || '"', 'null') ||
                    ',"status":' || COALESCE(CAST(NEW.STATUS AS VARCHAR(80)), 'null') ||
                    ',"tipo_cobranca":' || COALESCE(CAST(NEW.TIPO_COBRANCA AS VARCHAR(80)), 'null') || '}';
    IF (DELETING) THEN V_ANTES = '{"id_cobranca":' || COALESCE(CAST(OLD.ID_COBRANCA AS VARCHAR(80)), 'null') ||
                    ',"id_pagador":' || COALESCE(CAST(OLD.ID_PAGADOR AS VARCHAR(80)), 'null') ||
                    ',"id_recebedor":' || COALESCE(CAST(OLD.ID_RECEBEDOR AS VARCHAR(80)), 'null') ||
                    ',"valor":' || COALESCE(CAST(OLD.VALOR AS VARCHAR(80)), 'null') ||
                    ',"data_vencimento":' || COALESCE('"' || CAST(OLD.DATA_VENCIMENTO AS VARCHAR(80)) || '"', 'null') ||
                    ',"status":' || COALESCE(CAST(OLD.STATUS AS VARCHAR(80)), 'null') ||
                    ',"tipo_cobranca":' || COALESCE(CAST(OLD.TIPO_COBRANCA AS VARCHAR(80)), 'null') || '}';
    IF (UPDATING) THEN
    BEGIN
        V_ANTES = '';
        V_NOVO = '';
        IF (OLD.ID_COBRANCA IS DISTINCT FROM NEW.ID_COBRANCA) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_cobranca":' || COALESCE(CAST(OLD.ID_COBRANCA AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_cobranca":' || COALESCE(CAST(NEW.ID_COBRANCA AS VARCHAR(80)), 'null');
        END
        IF (OLD.ID_PAGADOR IS DISTINCT FROM NEW.ID_PAGADOR) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_pagador":' || COALESCE(CAST(OLD.ID_PAGADOR AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_pagador":' || COALESCE(CAST(NEW.ID_PAGADOR AS VARCHAR(80)), 'null');
        END
        IF (OLD.ID_RECEBEDOR IS DISTINCT FROM NEW.ID_RECEBEDOR) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_recebedor":' || COALESCE(CAST(OLD.ID_RECEBEDOR AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_recebedor":' || COALESCE(CAST(NEW.ID_RECEBEDOR AS VARCHAR(80)), 'null');
        END
        IF (OLD.VALOR IS DISTINCT FROM NEW.VALOR) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"valor":' || COALESCE(CAST(OLD.VALOR AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"valor":' || COALESCE(CAST(NEW.VALOR AS VARCHAR(80)), 'null');
        END
        IF (OLD.DATA_VENCIMENTO IS DISTINCT FROM NEW.DATA_VENCIMENTO) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"data_vencimento":' || COALESCE('"' || CAST(OLD.DATA_VENCIMENTO AS VARCHAR(80)) || '"', 'null');
            V_NOVO = V_NOVO || ',"data_vencimento":' || COALESCE('"' || CAST(NEW.DATA_VENCIMENTO AS VARCHAR(80)) || '"', 'null');
        END
        IF (OLD.STATUS IS DISTINCT FROM NEW.STATUS) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"status":' || COALESCE(CAST(OLD.STATUS AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"status":' || COALESCE(CAST(NEW.STATUS AS VARCHAR(80)), 'null');
        END
        IF (OLD.TIPO_COBRANCA IS DISTINCT FROM NEW.TIPO_COBRANCA) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"tipo_cobranca":' || COALESCE(CAST(OLD.TIPO_COBRANCA AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"tipo_cobranca":' || COALESCE(CAST(NEW.TIPO_COBRANCA AS VARCHAR(80)), 'null');
        END
        IF (V_ANTES <> '') THEN
        BEGIN
            V_ANTES = '{' || SUBSTRING(V_ANTES FROM 2) || '}';
            V_NOVO = '{' || SUBSTRING(V_NOVO FROM 2) || '}';
        END
        ELSE
        BEGIN
            V_ANTES = NULL;
            V_NOVO = NULL;
        END
    END

    EXECUTE STATEMENT (
        'INSERT INTO LOG (DATA_HORA, USUARIO, TABELA, ID_REGISTRO, ACAO, VALOR_ANTERIOR, VALOR_NOVO)
         VALUES (:data_hora, :usuario, ''COBRANCA'', :id_registro, :acao, :antes, :novo)'
    ) (
        data_hora := CURRENT_TIMESTAMP,
        usuario := COALESCE(RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_USUARIO_LOG'), RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_ID_USUARIO'), CURRENT_USER),
        id_registro := CASE WHEN DELETING THEN OLD.ID_COBRANCA ELSE NEW.ID_COBRANCA END,
        acao := CASE WHEN INSERTING THEN 'INSERT' WHEN UPDATING THEN 'UPDATE' ELSE 'DELETE' END,
        antes := :V_ANTES,
        novo := :V_NOVO
    )
    ON EXTERNAL DATA SOURCE :V_DESTINO
    AS USER :V_USUARIO PASSWORD :V_SENHA
    WITH COMMON TRANSACTION;
END^

CREATE OR ALTER TRIGGER TG_AIUD_CARTAO_LOG FOR CARTAO
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

    IF (INSERTING) THEN V_NOVO = '{"id_cartao":' || COALESCE(CAST(NEW.ID_CARTAO AS VARCHAR(80)), 'null') ||
                    ',"id_conta":' || COALESCE(CAST(NEW.ID_CONTA AS VARCHAR(80)), 'null') ||
                    ',"status":' || COALESCE(CAST(NEW.STATUS AS VARCHAR(80)), 'null') ||
                    ',"limite":' || COALESCE(CAST(NEW.LIMITE AS VARCHAR(80)), 'null') ||
                    ',"tentativas_pin":' || COALESCE(CAST(NEW.TENTATIVAS_PIN AS VARCHAR(80)), 'null') ||
                    ',"data_bloqueio":' || COALESCE('"' || CAST(NEW.DATA_BLOQUEIO AS VARCHAR(80)) || '"', 'null') || '}';
    IF (DELETING) THEN V_ANTES = '{"id_cartao":' || COALESCE(CAST(OLD.ID_CARTAO AS VARCHAR(80)), 'null') ||
                    ',"id_conta":' || COALESCE(CAST(OLD.ID_CONTA AS VARCHAR(80)), 'null') ||
                    ',"status":' || COALESCE(CAST(OLD.STATUS AS VARCHAR(80)), 'null') ||
                    ',"limite":' || COALESCE(CAST(OLD.LIMITE AS VARCHAR(80)), 'null') ||
                    ',"tentativas_pin":' || COALESCE(CAST(OLD.TENTATIVAS_PIN AS VARCHAR(80)), 'null') ||
                    ',"data_bloqueio":' || COALESCE('"' || CAST(OLD.DATA_BLOQUEIO AS VARCHAR(80)) || '"', 'null') || '}';
    IF (UPDATING) THEN
    BEGIN
        V_ANTES = '';
        V_NOVO = '';
        IF (OLD.ID_CARTAO IS DISTINCT FROM NEW.ID_CARTAO) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_cartao":' || COALESCE(CAST(OLD.ID_CARTAO AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_cartao":' || COALESCE(CAST(NEW.ID_CARTAO AS VARCHAR(80)), 'null');
        END
        IF (OLD.ID_CONTA IS DISTINCT FROM NEW.ID_CONTA) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_conta":' || COALESCE(CAST(OLD.ID_CONTA AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_conta":' || COALESCE(CAST(NEW.ID_CONTA AS VARCHAR(80)), 'null');
        END
        IF (OLD.STATUS IS DISTINCT FROM NEW.STATUS) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"status":' || COALESCE(CAST(OLD.STATUS AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"status":' || COALESCE(CAST(NEW.STATUS AS VARCHAR(80)), 'null');
        END
        IF (OLD.LIMITE IS DISTINCT FROM NEW.LIMITE) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"limite":' || COALESCE(CAST(OLD.LIMITE AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"limite":' || COALESCE(CAST(NEW.LIMITE AS VARCHAR(80)), 'null');
        END
        IF (OLD.TENTATIVAS_PIN IS DISTINCT FROM NEW.TENTATIVAS_PIN) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"tentativas_pin":' || COALESCE(CAST(OLD.TENTATIVAS_PIN AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"tentativas_pin":' || COALESCE(CAST(NEW.TENTATIVAS_PIN AS VARCHAR(80)), 'null');
        END
        IF (OLD.DATA_BLOQUEIO IS DISTINCT FROM NEW.DATA_BLOQUEIO) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"data_bloqueio":' || COALESCE('"' || CAST(OLD.DATA_BLOQUEIO AS VARCHAR(80)) || '"', 'null');
            V_NOVO = V_NOVO || ',"data_bloqueio":' || COALESCE('"' || CAST(NEW.DATA_BLOQUEIO AS VARCHAR(80)) || '"', 'null');
        END
        IF (V_ANTES <> '') THEN
        BEGIN
            V_ANTES = '{' || SUBSTRING(V_ANTES FROM 2) || '}';
            V_NOVO = '{' || SUBSTRING(V_NOVO FROM 2) || '}';
        END
        ELSE
        BEGIN
            V_ANTES = NULL;
            V_NOVO = NULL;
        END
    END

    EXECUTE STATEMENT (
        'INSERT INTO LOG (DATA_HORA, USUARIO, TABELA, ID_REGISTRO, ACAO, VALOR_ANTERIOR, VALOR_NOVO)
         VALUES (:data_hora, :usuario, ''CARTAO'', :id_registro, :acao, :antes, :novo)'
    ) (
        data_hora := CURRENT_TIMESTAMP,
        usuario := COALESCE(RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_USUARIO_LOG'), RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_ID_USUARIO'), CURRENT_USER),
        id_registro := CASE WHEN DELETING THEN OLD.ID_CARTAO ELSE NEW.ID_CARTAO END,
        acao := CASE WHEN INSERTING THEN 'INSERT' WHEN UPDATING THEN 'UPDATE' ELSE 'DELETE' END,
        antes := :V_ANTES,
        novo := :V_NOVO
    )
    ON EXTERNAL DATA SOURCE :V_DESTINO
    AS USER :V_USUARIO PASSWORD :V_SENHA
    WITH COMMON TRANSACTION;
END^

CREATE OR ALTER TRIGGER TG_AIUD_CHAVE_PIX_LOG FOR CHAVE_PIX
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

    IF (INSERTING) THEN V_NOVO = '{"id_chave_pix":' || COALESCE(CAST(NEW.ID_CHAVE_PIX AS VARCHAR(80)), 'null') ||
                    ',"id_conta":' || COALESCE(CAST(NEW.ID_CONTA AS VARCHAR(80)), 'null') || '}';
    IF (DELETING) THEN V_ANTES = '{"id_chave_pix":' || COALESCE(CAST(OLD.ID_CHAVE_PIX AS VARCHAR(80)), 'null') ||
                    ',"id_conta":' || COALESCE(CAST(OLD.ID_CONTA AS VARCHAR(80)), 'null') || '}';
    IF (UPDATING) THEN
    BEGIN
        V_ANTES = '';
        V_NOVO = '';
        IF (OLD.ID_CHAVE_PIX IS DISTINCT FROM NEW.ID_CHAVE_PIX) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_chave_pix":' || COALESCE(CAST(OLD.ID_CHAVE_PIX AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_chave_pix":' || COALESCE(CAST(NEW.ID_CHAVE_PIX AS VARCHAR(80)), 'null');
        END
        IF (OLD.ID_CONTA IS DISTINCT FROM NEW.ID_CONTA) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_conta":' || COALESCE(CAST(OLD.ID_CONTA AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_conta":' || COALESCE(CAST(NEW.ID_CONTA AS VARCHAR(80)), 'null');
        END
        IF (V_ANTES <> '') THEN
        BEGIN
            V_ANTES = '{' || SUBSTRING(V_ANTES FROM 2) || '}';
            V_NOVO = '{' || SUBSTRING(V_NOVO FROM 2) || '}';
        END
        ELSE
        BEGIN
            V_ANTES = NULL;
            V_NOVO = NULL;
        END
    END

    EXECUTE STATEMENT (
        'INSERT INTO LOG (DATA_HORA, USUARIO, TABELA, ID_REGISTRO, ACAO, VALOR_ANTERIOR, VALOR_NOVO)
         VALUES (:data_hora, :usuario, ''CHAVE_PIX'', :id_registro, :acao, :antes, :novo)'
    ) (
        data_hora := CURRENT_TIMESTAMP,
        usuario := COALESCE(RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_USUARIO_LOG'), RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_ID_USUARIO'), CURRENT_USER),
        id_registro := CASE WHEN DELETING THEN OLD.ID_CHAVE_PIX ELSE NEW.ID_CHAVE_PIX END,
        acao := CASE WHEN INSERTING THEN 'INSERT' WHEN UPDATING THEN 'UPDATE' ELSE 'DELETE' END,
        antes := :V_ANTES,
        novo := :V_NOVO
    )
    ON EXTERNAL DATA SOURCE :V_DESTINO
    AS USER :V_USUARIO PASSWORD :V_SENHA
    WITH COMMON TRANSACTION;
END^

CREATE OR ALTER TRIGGER TG_AIUD_COMPRA_LOG FOR COMPRA
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

    IF (INSERTING) THEN V_NOVO = '{"id_compra":' || COALESCE(CAST(NEW.ID_COMPRA AS VARCHAR(80)), 'null') ||
                    ',"id_cartao":' || COALESCE(CAST(NEW.ID_CARTAO AS VARCHAR(80)), 'null') ||
                    ',"valor_compra":' || COALESCE(CAST(NEW.VALOR_COMPRA AS VARCHAR(80)), 'null') ||
                    ',"tipo":' || COALESCE(CAST(NEW.TIPO AS VARCHAR(80)), 'null') ||
                    ',"valor_parcela":' || COALESCE(CAST(NEW.VALOR_PARCELA AS VARCHAR(80)), 'null') ||
                    ',"qtd_parcela":' || COALESCE(CAST(NEW.QTD_PARCELA AS VARCHAR(80)), 'null') ||
                    ',"data_compra":' || COALESCE('"' || CAST(NEW.DATA_COMPRA AS VARCHAR(80)) || '"', 'null') || '}';
    IF (DELETING) THEN V_ANTES = '{"id_compra":' || COALESCE(CAST(OLD.ID_COMPRA AS VARCHAR(80)), 'null') ||
                    ',"id_cartao":' || COALESCE(CAST(OLD.ID_CARTAO AS VARCHAR(80)), 'null') ||
                    ',"valor_compra":' || COALESCE(CAST(OLD.VALOR_COMPRA AS VARCHAR(80)), 'null') ||
                    ',"tipo":' || COALESCE(CAST(OLD.TIPO AS VARCHAR(80)), 'null') ||
                    ',"valor_parcela":' || COALESCE(CAST(OLD.VALOR_PARCELA AS VARCHAR(80)), 'null') ||
                    ',"qtd_parcela":' || COALESCE(CAST(OLD.QTD_PARCELA AS VARCHAR(80)), 'null') ||
                    ',"data_compra":' || COALESCE('"' || CAST(OLD.DATA_COMPRA AS VARCHAR(80)) || '"', 'null') || '}';
    IF (UPDATING) THEN
    BEGIN
        V_ANTES = '';
        V_NOVO = '';
        IF (OLD.ID_COMPRA IS DISTINCT FROM NEW.ID_COMPRA) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_compra":' || COALESCE(CAST(OLD.ID_COMPRA AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_compra":' || COALESCE(CAST(NEW.ID_COMPRA AS VARCHAR(80)), 'null');
        END
        IF (OLD.ID_CARTAO IS DISTINCT FROM NEW.ID_CARTAO) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_cartao":' || COALESCE(CAST(OLD.ID_CARTAO AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_cartao":' || COALESCE(CAST(NEW.ID_CARTAO AS VARCHAR(80)), 'null');
        END
        IF (OLD.VALOR_COMPRA IS DISTINCT FROM NEW.VALOR_COMPRA) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"valor_compra":' || COALESCE(CAST(OLD.VALOR_COMPRA AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"valor_compra":' || COALESCE(CAST(NEW.VALOR_COMPRA AS VARCHAR(80)), 'null');
        END
        IF (OLD.TIPO IS DISTINCT FROM NEW.TIPO) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"tipo":' || COALESCE(CAST(OLD.TIPO AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"tipo":' || COALESCE(CAST(NEW.TIPO AS VARCHAR(80)), 'null');
        END
        IF (OLD.VALOR_PARCELA IS DISTINCT FROM NEW.VALOR_PARCELA) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"valor_parcela":' || COALESCE(CAST(OLD.VALOR_PARCELA AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"valor_parcela":' || COALESCE(CAST(NEW.VALOR_PARCELA AS VARCHAR(80)), 'null');
        END
        IF (OLD.QTD_PARCELA IS DISTINCT FROM NEW.QTD_PARCELA) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"qtd_parcela":' || COALESCE(CAST(OLD.QTD_PARCELA AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"qtd_parcela":' || COALESCE(CAST(NEW.QTD_PARCELA AS VARCHAR(80)), 'null');
        END
        IF (OLD.DATA_COMPRA IS DISTINCT FROM NEW.DATA_COMPRA) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"data_compra":' || COALESCE('"' || CAST(OLD.DATA_COMPRA AS VARCHAR(80)) || '"', 'null');
            V_NOVO = V_NOVO || ',"data_compra":' || COALESCE('"' || CAST(NEW.DATA_COMPRA AS VARCHAR(80)) || '"', 'null');
        END
        IF (V_ANTES <> '') THEN
        BEGIN
            V_ANTES = '{' || SUBSTRING(V_ANTES FROM 2) || '}';
            V_NOVO = '{' || SUBSTRING(V_NOVO FROM 2) || '}';
        END
        ELSE
        BEGIN
            V_ANTES = NULL;
            V_NOVO = NULL;
        END
    END

    EXECUTE STATEMENT (
        'INSERT INTO LOG (DATA_HORA, USUARIO, TABELA, ID_REGISTRO, ACAO, VALOR_ANTERIOR, VALOR_NOVO)
         VALUES (:data_hora, :usuario, ''COMPRA'', :id_registro, :acao, :antes, :novo)'
    ) (
        data_hora := CURRENT_TIMESTAMP,
        usuario := COALESCE(RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_USUARIO_LOG'), RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_ID_USUARIO'), CURRENT_USER),
        id_registro := CASE WHEN DELETING THEN OLD.ID_COMPRA ELSE NEW.ID_COMPRA END,
        acao := CASE WHEN INSERTING THEN 'INSERT' WHEN UPDATING THEN 'UPDATE' ELSE 'DELETE' END,
        antes := :V_ANTES,
        novo := :V_NOVO
    )
    ON EXTERNAL DATA SOURCE :V_DESTINO
    AS USER :V_USUARIO PASSWORD :V_SENHA
    WITH COMMON TRANSACTION;
END^

CREATE OR ALTER TRIGGER TG_AIUD_FATURA_LOG FOR FATURA
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

    IF (INSERTING) THEN V_NOVO = '{"id_fatura":' || COALESCE(CAST(NEW.ID_FATURA AS VARCHAR(80)), 'null') ||
                    ',"id_conta":' || COALESCE(CAST(NEW.ID_CONTA AS VARCHAR(80)), 'null') ||
                    ',"valor_total":' || COALESCE(CAST(NEW.VALOR_TOTAL AS VARCHAR(80)), 'null') ||
                    ',"status":' || COALESCE(CAST(NEW.STATUS AS VARCHAR(80)), 'null') ||
                    ',"data_fechamento":' || COALESCE('"' || CAST(NEW.DATA_FECHAMENTO AS VARCHAR(80)) || '"', 'null') ||
                    ',"data_vencimento":' || COALESCE('"' || CAST(NEW.DATA_VENCIMENTO AS VARCHAR(80)) || '"', 'null') || '}';
    IF (DELETING) THEN V_ANTES = '{"id_fatura":' || COALESCE(CAST(OLD.ID_FATURA AS VARCHAR(80)), 'null') ||
                    ',"id_conta":' || COALESCE(CAST(OLD.ID_CONTA AS VARCHAR(80)), 'null') ||
                    ',"valor_total":' || COALESCE(CAST(OLD.VALOR_TOTAL AS VARCHAR(80)), 'null') ||
                    ',"status":' || COALESCE(CAST(OLD.STATUS AS VARCHAR(80)), 'null') ||
                    ',"data_fechamento":' || COALESCE('"' || CAST(OLD.DATA_FECHAMENTO AS VARCHAR(80)) || '"', 'null') ||
                    ',"data_vencimento":' || COALESCE('"' || CAST(OLD.DATA_VENCIMENTO AS VARCHAR(80)) || '"', 'null') || '}';
    IF (UPDATING) THEN
    BEGIN
        V_ANTES = '';
        V_NOVO = '';
        IF (OLD.ID_FATURA IS DISTINCT FROM NEW.ID_FATURA) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_fatura":' || COALESCE(CAST(OLD.ID_FATURA AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_fatura":' || COALESCE(CAST(NEW.ID_FATURA AS VARCHAR(80)), 'null');
        END
        IF (OLD.ID_CONTA IS DISTINCT FROM NEW.ID_CONTA) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_conta":' || COALESCE(CAST(OLD.ID_CONTA AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_conta":' || COALESCE(CAST(NEW.ID_CONTA AS VARCHAR(80)), 'null');
        END
        IF (OLD.VALOR_TOTAL IS DISTINCT FROM NEW.VALOR_TOTAL) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"valor_total":' || COALESCE(CAST(OLD.VALOR_TOTAL AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"valor_total":' || COALESCE(CAST(NEW.VALOR_TOTAL AS VARCHAR(80)), 'null');
        END
        IF (OLD.STATUS IS DISTINCT FROM NEW.STATUS) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"status":' || COALESCE(CAST(OLD.STATUS AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"status":' || COALESCE(CAST(NEW.STATUS AS VARCHAR(80)), 'null');
        END
        IF (OLD.DATA_FECHAMENTO IS DISTINCT FROM NEW.DATA_FECHAMENTO) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"data_fechamento":' || COALESCE('"' || CAST(OLD.DATA_FECHAMENTO AS VARCHAR(80)) || '"', 'null');
            V_NOVO = V_NOVO || ',"data_fechamento":' || COALESCE('"' || CAST(NEW.DATA_FECHAMENTO AS VARCHAR(80)) || '"', 'null');
        END
        IF (OLD.DATA_VENCIMENTO IS DISTINCT FROM NEW.DATA_VENCIMENTO) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"data_vencimento":' || COALESCE('"' || CAST(OLD.DATA_VENCIMENTO AS VARCHAR(80)) || '"', 'null');
            V_NOVO = V_NOVO || ',"data_vencimento":' || COALESCE('"' || CAST(NEW.DATA_VENCIMENTO AS VARCHAR(80)) || '"', 'null');
        END
        IF (V_ANTES <> '') THEN
        BEGIN
            V_ANTES = '{' || SUBSTRING(V_ANTES FROM 2) || '}';
            V_NOVO = '{' || SUBSTRING(V_NOVO FROM 2) || '}';
        END
        ELSE
        BEGIN
            V_ANTES = NULL;
            V_NOVO = NULL;
        END
    END

    EXECUTE STATEMENT (
        'INSERT INTO LOG (DATA_HORA, USUARIO, TABELA, ID_REGISTRO, ACAO, VALOR_ANTERIOR, VALOR_NOVO)
         VALUES (:data_hora, :usuario, ''FATURA'', :id_registro, :acao, :antes, :novo)'
    ) (
        data_hora := CURRENT_TIMESTAMP,
        usuario := COALESCE(RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_USUARIO_LOG'), RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_ID_USUARIO'), CURRENT_USER),
        id_registro := CASE WHEN DELETING THEN OLD.ID_FATURA ELSE NEW.ID_FATURA END,
        acao := CASE WHEN INSERTING THEN 'INSERT' WHEN UPDATING THEN 'UPDATE' ELSE 'DELETE' END,
        antes := :V_ANTES,
        novo := :V_NOVO
    )
    ON EXTERNAL DATA SOURCE :V_DESTINO
    AS USER :V_USUARIO PASSWORD :V_SENHA
    WITH COMMON TRANSACTION;
END^

CREATE OR ALTER TRIGGER TG_AIUD_AGENDAMENTO_FINANCEIRO_LOG FOR AGENDAMENTO_FINANCEIRO
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

    IF (INSERTING) THEN V_NOVO = '{"id_agendamento":' || COALESCE(CAST(NEW.ID_AGENDAMENTO AS VARCHAR(80)), 'null') ||
                    ',"id_usuario":' || COALESCE(CAST(NEW.ID_USUARIO AS VARCHAR(80)), 'null') ||
                    ',"id_conta":' || COALESCE(CAST(NEW.ID_CONTA AS VARCHAR(80)), 'null') ||
                    ',"id_conta_destino":' || COALESCE(CAST(NEW.ID_CONTA_DESTINO AS VARCHAR(80)), 'null') ||
                    ',"id_cobranca":' || COALESCE(CAST(NEW.ID_COBRANCA AS VARCHAR(80)), 'null') ||
                    ',"valor":' || COALESCE(CAST(NEW.VALOR AS VARCHAR(80)), 'null') ||
                    ',"data_agendada":' || COALESCE('"' || CAST(NEW.DATA_AGENDADA AS VARCHAR(80)) || '"', 'null') ||
                    ',"status":' || COALESCE('"' || REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(CAST(NEW.STATUS AS VARCHAR(80)), ASCII_CHAR(92), ASCII_CHAR(92) || ASCII_CHAR(92)), ASCII_CHAR(34), ASCII_CHAR(92) || ASCII_CHAR(34)), ASCII_CHAR(13), ASCII_CHAR(92) || 'r'), ASCII_CHAR(10), ASCII_CHAR(92) || 'n'), ASCII_CHAR(9), ASCII_CHAR(92) || 't') || '"', 'null') ||
                    ',"tentativas":' || COALESCE(CAST(NEW.TENTATIVAS AS VARCHAR(80)), 'null') || '}';
    IF (DELETING) THEN V_ANTES = '{"id_agendamento":' || COALESCE(CAST(OLD.ID_AGENDAMENTO AS VARCHAR(80)), 'null') ||
                    ',"id_usuario":' || COALESCE(CAST(OLD.ID_USUARIO AS VARCHAR(80)), 'null') ||
                    ',"id_conta":' || COALESCE(CAST(OLD.ID_CONTA AS VARCHAR(80)), 'null') ||
                    ',"id_conta_destino":' || COALESCE(CAST(OLD.ID_CONTA_DESTINO AS VARCHAR(80)), 'null') ||
                    ',"id_cobranca":' || COALESCE(CAST(OLD.ID_COBRANCA AS VARCHAR(80)), 'null') ||
                    ',"valor":' || COALESCE(CAST(OLD.VALOR AS VARCHAR(80)), 'null') ||
                    ',"data_agendada":' || COALESCE('"' || CAST(OLD.DATA_AGENDADA AS VARCHAR(80)) || '"', 'null') ||
                    ',"status":' || COALESCE('"' || REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(CAST(OLD.STATUS AS VARCHAR(80)), ASCII_CHAR(92), ASCII_CHAR(92) || ASCII_CHAR(92)), ASCII_CHAR(34), ASCII_CHAR(92) || ASCII_CHAR(34)), ASCII_CHAR(13), ASCII_CHAR(92) || 'r'), ASCII_CHAR(10), ASCII_CHAR(92) || 'n'), ASCII_CHAR(9), ASCII_CHAR(92) || 't') || '"', 'null') ||
                    ',"tentativas":' || COALESCE(CAST(OLD.TENTATIVAS AS VARCHAR(80)), 'null') || '}';
    IF (UPDATING) THEN
    BEGIN
        V_ANTES = '';
        V_NOVO = '';
        IF (OLD.ID_AGENDAMENTO IS DISTINCT FROM NEW.ID_AGENDAMENTO) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_agendamento":' || COALESCE(CAST(OLD.ID_AGENDAMENTO AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_agendamento":' || COALESCE(CAST(NEW.ID_AGENDAMENTO AS VARCHAR(80)), 'null');
        END
        IF (OLD.ID_USUARIO IS DISTINCT FROM NEW.ID_USUARIO) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_usuario":' || COALESCE(CAST(OLD.ID_USUARIO AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_usuario":' || COALESCE(CAST(NEW.ID_USUARIO AS VARCHAR(80)), 'null');
        END
        IF (OLD.ID_CONTA IS DISTINCT FROM NEW.ID_CONTA) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_conta":' || COALESCE(CAST(OLD.ID_CONTA AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_conta":' || COALESCE(CAST(NEW.ID_CONTA AS VARCHAR(80)), 'null');
        END
        IF (OLD.ID_CONTA_DESTINO IS DISTINCT FROM NEW.ID_CONTA_DESTINO) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_conta_destino":' || COALESCE(CAST(OLD.ID_CONTA_DESTINO AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_conta_destino":' || COALESCE(CAST(NEW.ID_CONTA_DESTINO AS VARCHAR(80)), 'null');
        END
        IF (OLD.ID_COBRANCA IS DISTINCT FROM NEW.ID_COBRANCA) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_cobranca":' || COALESCE(CAST(OLD.ID_COBRANCA AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_cobranca":' || COALESCE(CAST(NEW.ID_COBRANCA AS VARCHAR(80)), 'null');
        END
        IF (OLD.VALOR IS DISTINCT FROM NEW.VALOR) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"valor":' || COALESCE(CAST(OLD.VALOR AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"valor":' || COALESCE(CAST(NEW.VALOR AS VARCHAR(80)), 'null');
        END
        IF (OLD.DATA_AGENDADA IS DISTINCT FROM NEW.DATA_AGENDADA) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"data_agendada":' || COALESCE('"' || CAST(OLD.DATA_AGENDADA AS VARCHAR(80)) || '"', 'null');
            V_NOVO = V_NOVO || ',"data_agendada":' || COALESCE('"' || CAST(NEW.DATA_AGENDADA AS VARCHAR(80)) || '"', 'null');
        END
        IF (OLD.STATUS IS DISTINCT FROM NEW.STATUS) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"status":' || COALESCE('"' || REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(CAST(OLD.STATUS AS VARCHAR(80)), ASCII_CHAR(92), ASCII_CHAR(92) || ASCII_CHAR(92)), ASCII_CHAR(34), ASCII_CHAR(92) || ASCII_CHAR(34)), ASCII_CHAR(13), ASCII_CHAR(92) || 'r'), ASCII_CHAR(10), ASCII_CHAR(92) || 'n'), ASCII_CHAR(9), ASCII_CHAR(92) || 't') || '"', 'null');
            V_NOVO = V_NOVO || ',"status":' || COALESCE('"' || REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(CAST(NEW.STATUS AS VARCHAR(80)), ASCII_CHAR(92), ASCII_CHAR(92) || ASCII_CHAR(92)), ASCII_CHAR(34), ASCII_CHAR(92) || ASCII_CHAR(34)), ASCII_CHAR(13), ASCII_CHAR(92) || 'r'), ASCII_CHAR(10), ASCII_CHAR(92) || 'n'), ASCII_CHAR(9), ASCII_CHAR(92) || 't') || '"', 'null');
        END
        IF (OLD.TENTATIVAS IS DISTINCT FROM NEW.TENTATIVAS) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"tentativas":' || COALESCE(CAST(OLD.TENTATIVAS AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"tentativas":' || COALESCE(CAST(NEW.TENTATIVAS AS VARCHAR(80)), 'null');
        END
        IF (V_ANTES <> '') THEN
        BEGIN
            V_ANTES = '{' || SUBSTRING(V_ANTES FROM 2) || '}';
            V_NOVO = '{' || SUBSTRING(V_NOVO FROM 2) || '}';
        END
        ELSE
        BEGIN
            V_ANTES = NULL;
            V_NOVO = NULL;
        END
    END

    EXECUTE STATEMENT (
        'INSERT INTO LOG (DATA_HORA, USUARIO, TABELA, ID_REGISTRO, ACAO, VALOR_ANTERIOR, VALOR_NOVO)
         VALUES (:data_hora, :usuario, ''AGENDAMENTO_FINANCEIRO'', :id_registro, :acao, :antes, :novo)'
    ) (
        data_hora := CURRENT_TIMESTAMP,
        usuario := COALESCE(RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_USUARIO_LOG'), RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_ID_USUARIO'), CURRENT_USER),
        id_registro := CASE WHEN DELETING THEN OLD.ID_AGENDAMENTO ELSE NEW.ID_AGENDAMENTO END,
        acao := CASE WHEN INSERTING THEN 'INSERT' WHEN UPDATING THEN 'UPDATE' ELSE 'DELETE' END,
        antes := :V_ANTES,
        novo := :V_NOVO
    )
    ON EXTERNAL DATA SOURCE :V_DESTINO
    AS USER :V_USUARIO PASSWORD :V_SENHA
    WITH COMMON TRANSACTION;
END^

CREATE OR ALTER TRIGGER TG_AIUD_RECORRENCIA_FINANCEIRA_LOG FOR RECORRENCIA_FINANCEIRA
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

    IF (INSERTING) THEN V_NOVO = '{"id_recorrencia":' || COALESCE(CAST(NEW.ID_RECORRENCIA AS VARCHAR(80)), 'null') ||
                    ',"id_usuario":' || COALESCE(CAST(NEW.ID_USUARIO AS VARCHAR(80)), 'null') ||
                    ',"id_conta":' || COALESCE(CAST(NEW.ID_CONTA AS VARCHAR(80)), 'null') ||
                    ',"id_conta_destino":' || COALESCE(CAST(NEW.ID_CONTA_DESTINO AS VARCHAR(80)), 'null') ||
                    ',"id_cobranca":' || COALESCE(CAST(NEW.ID_COBRANCA AS VARCHAR(80)), 'null') ||
                    ',"valor":' || COALESCE(CAST(NEW.VALOR AS VARCHAR(80)), 'null') ||
                    ',"frequencia":' || COALESCE('"' || REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(CAST(NEW.FREQUENCIA AS VARCHAR(80)), ASCII_CHAR(92), ASCII_CHAR(92) || ASCII_CHAR(92)), ASCII_CHAR(34), ASCII_CHAR(92) || ASCII_CHAR(34)), ASCII_CHAR(13), ASCII_CHAR(92) || 'r'), ASCII_CHAR(10), ASCII_CHAR(92) || 'n'), ASCII_CHAR(9), ASCII_CHAR(92) || 't') || '"', 'null') ||
                    ',"data_inicial":' || COALESCE('"' || CAST(NEW.DATA_INICIAL AS VARCHAR(80)) || '"', 'null') ||
                    ',"data_final":' || COALESCE('"' || CAST(NEW.DATA_FINAL AS VARCHAR(80)) || '"', 'null') ||
                    ',"limite_execucoes":' || COALESCE(CAST(NEW.LIMITE_EXECUCOES AS VARCHAR(80)), 'null') ||
                    ',"execucoes_criadas":' || COALESCE(CAST(NEW.EXECUCOES_CRIADAS AS VARCHAR(80)), 'null') ||
                    ',"proxima_execucao":' || COALESCE('"' || CAST(NEW.PROXIMA_EXECUCAO AS VARCHAR(80)) || '"', 'null') ||
                    ',"status":' || COALESCE('"' || REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(CAST(NEW.STATUS AS VARCHAR(80)), ASCII_CHAR(92), ASCII_CHAR(92) || ASCII_CHAR(92)), ASCII_CHAR(34), ASCII_CHAR(92) || ASCII_CHAR(34)), ASCII_CHAR(13), ASCII_CHAR(92) || 'r'), ASCII_CHAR(10), ASCII_CHAR(92) || 'n'), ASCII_CHAR(9), ASCII_CHAR(92) || 't') || '"', 'null') || '}';
    IF (DELETING) THEN V_ANTES = '{"id_recorrencia":' || COALESCE(CAST(OLD.ID_RECORRENCIA AS VARCHAR(80)), 'null') ||
                    ',"id_usuario":' || COALESCE(CAST(OLD.ID_USUARIO AS VARCHAR(80)), 'null') ||
                    ',"id_conta":' || COALESCE(CAST(OLD.ID_CONTA AS VARCHAR(80)), 'null') ||
                    ',"id_conta_destino":' || COALESCE(CAST(OLD.ID_CONTA_DESTINO AS VARCHAR(80)), 'null') ||
                    ',"id_cobranca":' || COALESCE(CAST(OLD.ID_COBRANCA AS VARCHAR(80)), 'null') ||
                    ',"valor":' || COALESCE(CAST(OLD.VALOR AS VARCHAR(80)), 'null') ||
                    ',"frequencia":' || COALESCE('"' || REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(CAST(OLD.FREQUENCIA AS VARCHAR(80)), ASCII_CHAR(92), ASCII_CHAR(92) || ASCII_CHAR(92)), ASCII_CHAR(34), ASCII_CHAR(92) || ASCII_CHAR(34)), ASCII_CHAR(13), ASCII_CHAR(92) || 'r'), ASCII_CHAR(10), ASCII_CHAR(92) || 'n'), ASCII_CHAR(9), ASCII_CHAR(92) || 't') || '"', 'null') ||
                    ',"data_inicial":' || COALESCE('"' || CAST(OLD.DATA_INICIAL AS VARCHAR(80)) || '"', 'null') ||
                    ',"data_final":' || COALESCE('"' || CAST(OLD.DATA_FINAL AS VARCHAR(80)) || '"', 'null') ||
                    ',"limite_execucoes":' || COALESCE(CAST(OLD.LIMITE_EXECUCOES AS VARCHAR(80)), 'null') ||
                    ',"execucoes_criadas":' || COALESCE(CAST(OLD.EXECUCOES_CRIADAS AS VARCHAR(80)), 'null') ||
                    ',"proxima_execucao":' || COALESCE('"' || CAST(OLD.PROXIMA_EXECUCAO AS VARCHAR(80)) || '"', 'null') ||
                    ',"status":' || COALESCE('"' || REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(CAST(OLD.STATUS AS VARCHAR(80)), ASCII_CHAR(92), ASCII_CHAR(92) || ASCII_CHAR(92)), ASCII_CHAR(34), ASCII_CHAR(92) || ASCII_CHAR(34)), ASCII_CHAR(13), ASCII_CHAR(92) || 'r'), ASCII_CHAR(10), ASCII_CHAR(92) || 'n'), ASCII_CHAR(9), ASCII_CHAR(92) || 't') || '"', 'null') || '}';
    IF (UPDATING) THEN
    BEGIN
        V_ANTES = '';
        V_NOVO = '';
        IF (OLD.ID_RECORRENCIA IS DISTINCT FROM NEW.ID_RECORRENCIA) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_recorrencia":' || COALESCE(CAST(OLD.ID_RECORRENCIA AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_recorrencia":' || COALESCE(CAST(NEW.ID_RECORRENCIA AS VARCHAR(80)), 'null');
        END
        IF (OLD.ID_USUARIO IS DISTINCT FROM NEW.ID_USUARIO) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_usuario":' || COALESCE(CAST(OLD.ID_USUARIO AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_usuario":' || COALESCE(CAST(NEW.ID_USUARIO AS VARCHAR(80)), 'null');
        END
        IF (OLD.ID_CONTA IS DISTINCT FROM NEW.ID_CONTA) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_conta":' || COALESCE(CAST(OLD.ID_CONTA AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_conta":' || COALESCE(CAST(NEW.ID_CONTA AS VARCHAR(80)), 'null');
        END
        IF (OLD.ID_CONTA_DESTINO IS DISTINCT FROM NEW.ID_CONTA_DESTINO) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_conta_destino":' || COALESCE(CAST(OLD.ID_CONTA_DESTINO AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_conta_destino":' || COALESCE(CAST(NEW.ID_CONTA_DESTINO AS VARCHAR(80)), 'null');
        END
        IF (OLD.ID_COBRANCA IS DISTINCT FROM NEW.ID_COBRANCA) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_cobranca":' || COALESCE(CAST(OLD.ID_COBRANCA AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_cobranca":' || COALESCE(CAST(NEW.ID_COBRANCA AS VARCHAR(80)), 'null');
        END
        IF (OLD.VALOR IS DISTINCT FROM NEW.VALOR) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"valor":' || COALESCE(CAST(OLD.VALOR AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"valor":' || COALESCE(CAST(NEW.VALOR AS VARCHAR(80)), 'null');
        END
        IF (OLD.FREQUENCIA IS DISTINCT FROM NEW.FREQUENCIA) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"frequencia":' || COALESCE('"' || REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(CAST(OLD.FREQUENCIA AS VARCHAR(80)), ASCII_CHAR(92), ASCII_CHAR(92) || ASCII_CHAR(92)), ASCII_CHAR(34), ASCII_CHAR(92) || ASCII_CHAR(34)), ASCII_CHAR(13), ASCII_CHAR(92) || 'r'), ASCII_CHAR(10), ASCII_CHAR(92) || 'n'), ASCII_CHAR(9), ASCII_CHAR(92) || 't') || '"', 'null');
            V_NOVO = V_NOVO || ',"frequencia":' || COALESCE('"' || REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(CAST(NEW.FREQUENCIA AS VARCHAR(80)), ASCII_CHAR(92), ASCII_CHAR(92) || ASCII_CHAR(92)), ASCII_CHAR(34), ASCII_CHAR(92) || ASCII_CHAR(34)), ASCII_CHAR(13), ASCII_CHAR(92) || 'r'), ASCII_CHAR(10), ASCII_CHAR(92) || 'n'), ASCII_CHAR(9), ASCII_CHAR(92) || 't') || '"', 'null');
        END
        IF (OLD.DATA_INICIAL IS DISTINCT FROM NEW.DATA_INICIAL) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"data_inicial":' || COALESCE('"' || CAST(OLD.DATA_INICIAL AS VARCHAR(80)) || '"', 'null');
            V_NOVO = V_NOVO || ',"data_inicial":' || COALESCE('"' || CAST(NEW.DATA_INICIAL AS VARCHAR(80)) || '"', 'null');
        END
        IF (OLD.DATA_FINAL IS DISTINCT FROM NEW.DATA_FINAL) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"data_final":' || COALESCE('"' || CAST(OLD.DATA_FINAL AS VARCHAR(80)) || '"', 'null');
            V_NOVO = V_NOVO || ',"data_final":' || COALESCE('"' || CAST(NEW.DATA_FINAL AS VARCHAR(80)) || '"', 'null');
        END
        IF (OLD.LIMITE_EXECUCOES IS DISTINCT FROM NEW.LIMITE_EXECUCOES) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"limite_execucoes":' || COALESCE(CAST(OLD.LIMITE_EXECUCOES AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"limite_execucoes":' || COALESCE(CAST(NEW.LIMITE_EXECUCOES AS VARCHAR(80)), 'null');
        END
        IF (OLD.EXECUCOES_CRIADAS IS DISTINCT FROM NEW.EXECUCOES_CRIADAS) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"execucoes_criadas":' || COALESCE(CAST(OLD.EXECUCOES_CRIADAS AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"execucoes_criadas":' || COALESCE(CAST(NEW.EXECUCOES_CRIADAS AS VARCHAR(80)), 'null');
        END
        IF (OLD.PROXIMA_EXECUCAO IS DISTINCT FROM NEW.PROXIMA_EXECUCAO) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"proxima_execucao":' || COALESCE('"' || CAST(OLD.PROXIMA_EXECUCAO AS VARCHAR(80)) || '"', 'null');
            V_NOVO = V_NOVO || ',"proxima_execucao":' || COALESCE('"' || CAST(NEW.PROXIMA_EXECUCAO AS VARCHAR(80)) || '"', 'null');
        END
        IF (OLD.STATUS IS DISTINCT FROM NEW.STATUS) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"status":' || COALESCE('"' || REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(CAST(OLD.STATUS AS VARCHAR(80)), ASCII_CHAR(92), ASCII_CHAR(92) || ASCII_CHAR(92)), ASCII_CHAR(34), ASCII_CHAR(92) || ASCII_CHAR(34)), ASCII_CHAR(13), ASCII_CHAR(92) || 'r'), ASCII_CHAR(10), ASCII_CHAR(92) || 'n'), ASCII_CHAR(9), ASCII_CHAR(92) || 't') || '"', 'null');
            V_NOVO = V_NOVO || ',"status":' || COALESCE('"' || REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(CAST(NEW.STATUS AS VARCHAR(80)), ASCII_CHAR(92), ASCII_CHAR(92) || ASCII_CHAR(92)), ASCII_CHAR(34), ASCII_CHAR(92) || ASCII_CHAR(34)), ASCII_CHAR(13), ASCII_CHAR(92) || 'r'), ASCII_CHAR(10), ASCII_CHAR(92) || 'n'), ASCII_CHAR(9), ASCII_CHAR(92) || 't') || '"', 'null');
        END
        IF (V_ANTES <> '') THEN
        BEGIN
            V_ANTES = '{' || SUBSTRING(V_ANTES FROM 2) || '}';
            V_NOVO = '{' || SUBSTRING(V_NOVO FROM 2) || '}';
        END
        ELSE
        BEGIN
            V_ANTES = NULL;
            V_NOVO = NULL;
        END
    END

    EXECUTE STATEMENT (
        'INSERT INTO LOG (DATA_HORA, USUARIO, TABELA, ID_REGISTRO, ACAO, VALOR_ANTERIOR, VALOR_NOVO)
         VALUES (:data_hora, :usuario, ''RECORRENCIA_FINANCEIRA'', :id_registro, :acao, :antes, :novo)'
    ) (
        data_hora := CURRENT_TIMESTAMP,
        usuario := COALESCE(RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_USUARIO_LOG'), RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_ID_USUARIO'), CURRENT_USER),
        id_registro := CASE WHEN DELETING THEN OLD.ID_RECORRENCIA ELSE NEW.ID_RECORRENCIA END,
        acao := CASE WHEN INSERTING THEN 'INSERT' WHEN UPDATING THEN 'UPDATE' ELSE 'DELETE' END,
        antes := :V_ANTES,
        novo := :V_NOVO
    )
    ON EXTERNAL DATA SOURCE :V_DESTINO
    AS USER :V_USUARIO PASSWORD :V_SENHA
    WITH COMMON TRANSACTION;
END^

CREATE OR ALTER TRIGGER TG_AIUD_ESTORNO_FINANCEIRO_LOG FOR ESTORNO_FINANCEIRO
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

    IF (INSERTING) THEN V_NOVO = '{"id_estorno":' || COALESCE(CAST(NEW.ID_ESTORNO AS VARCHAR(80)), 'null') ||
                    ',"id_cobranca":' || COALESCE(CAST(NEW.ID_COBRANCA AS VARCHAR(80)), 'null') ||
                    ',"id_movimentacao_original":' || COALESCE(CAST(NEW.ID_MOVIMENTACAO_ORIGINAL AS VARCHAR(80)), 'null') ||
                    ',"id_movimentacao_reversa":' || COALESCE(CAST(NEW.ID_MOVIMENTACAO_REVERSA AS VARCHAR(80)), 'null') ||
                    ',"id_conta_solicitante":' || COALESCE(CAST(NEW.ID_CONTA_SOLICITANTE AS VARCHAR(80)), 'null') ||
                    ',"id_usuario_responsavel":' || COALESCE(CAST(NEW.ID_USUARIO_RESPONSAVEL AS VARCHAR(80)), 'null') ||
                    ',"id_conta_pagador":' || COALESCE(CAST(NEW.ID_CONTA_PAGADOR AS VARCHAR(80)), 'null') ||
                    ',"id_conta_recebedor":' || COALESCE(CAST(NEW.ID_CONTA_RECEBEDOR AS VARCHAR(80)), 'null') ||
                    ',"valor":' || COALESCE(CAST(NEW.VALOR AS VARCHAR(80)), 'null') ||
                    ',"status":' || COALESCE('"' || REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(CAST(NEW.STATUS AS VARCHAR(80)), ASCII_CHAR(92), ASCII_CHAR(92) || ASCII_CHAR(92)), ASCII_CHAR(34), ASCII_CHAR(92) || ASCII_CHAR(34)), ASCII_CHAR(13), ASCII_CHAR(92) || 'r'), ASCII_CHAR(10), ASCII_CHAR(92) || 'n'), ASCII_CHAR(9), ASCII_CHAR(92) || 't') || '"', 'null') || '}';
    IF (DELETING) THEN V_ANTES = '{"id_estorno":' || COALESCE(CAST(OLD.ID_ESTORNO AS VARCHAR(80)), 'null') ||
                    ',"id_cobranca":' || COALESCE(CAST(OLD.ID_COBRANCA AS VARCHAR(80)), 'null') ||
                    ',"id_movimentacao_original":' || COALESCE(CAST(OLD.ID_MOVIMENTACAO_ORIGINAL AS VARCHAR(80)), 'null') ||
                    ',"id_movimentacao_reversa":' || COALESCE(CAST(OLD.ID_MOVIMENTACAO_REVERSA AS VARCHAR(80)), 'null') ||
                    ',"id_conta_solicitante":' || COALESCE(CAST(OLD.ID_CONTA_SOLICITANTE AS VARCHAR(80)), 'null') ||
                    ',"id_usuario_responsavel":' || COALESCE(CAST(OLD.ID_USUARIO_RESPONSAVEL AS VARCHAR(80)), 'null') ||
                    ',"id_conta_pagador":' || COALESCE(CAST(OLD.ID_CONTA_PAGADOR AS VARCHAR(80)), 'null') ||
                    ',"id_conta_recebedor":' || COALESCE(CAST(OLD.ID_CONTA_RECEBEDOR AS VARCHAR(80)), 'null') ||
                    ',"valor":' || COALESCE(CAST(OLD.VALOR AS VARCHAR(80)), 'null') ||
                    ',"status":' || COALESCE('"' || REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(CAST(OLD.STATUS AS VARCHAR(80)), ASCII_CHAR(92), ASCII_CHAR(92) || ASCII_CHAR(92)), ASCII_CHAR(34), ASCII_CHAR(92) || ASCII_CHAR(34)), ASCII_CHAR(13), ASCII_CHAR(92) || 'r'), ASCII_CHAR(10), ASCII_CHAR(92) || 'n'), ASCII_CHAR(9), ASCII_CHAR(92) || 't') || '"', 'null') || '}';
    IF (UPDATING) THEN
    BEGIN
        V_ANTES = '';
        V_NOVO = '';
        IF (OLD.ID_ESTORNO IS DISTINCT FROM NEW.ID_ESTORNO) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_estorno":' || COALESCE(CAST(OLD.ID_ESTORNO AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_estorno":' || COALESCE(CAST(NEW.ID_ESTORNO AS VARCHAR(80)), 'null');
        END
        IF (OLD.ID_COBRANCA IS DISTINCT FROM NEW.ID_COBRANCA) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_cobranca":' || COALESCE(CAST(OLD.ID_COBRANCA AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_cobranca":' || COALESCE(CAST(NEW.ID_COBRANCA AS VARCHAR(80)), 'null');
        END
        IF (OLD.ID_MOVIMENTACAO_ORIGINAL IS DISTINCT FROM NEW.ID_MOVIMENTACAO_ORIGINAL) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_movimentacao_original":' || COALESCE(CAST(OLD.ID_MOVIMENTACAO_ORIGINAL AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_movimentacao_original":' || COALESCE(CAST(NEW.ID_MOVIMENTACAO_ORIGINAL AS VARCHAR(80)), 'null');
        END
        IF (OLD.ID_MOVIMENTACAO_REVERSA IS DISTINCT FROM NEW.ID_MOVIMENTACAO_REVERSA) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_movimentacao_reversa":' || COALESCE(CAST(OLD.ID_MOVIMENTACAO_REVERSA AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_movimentacao_reversa":' || COALESCE(CAST(NEW.ID_MOVIMENTACAO_REVERSA AS VARCHAR(80)), 'null');
        END
        IF (OLD.ID_CONTA_SOLICITANTE IS DISTINCT FROM NEW.ID_CONTA_SOLICITANTE) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_conta_solicitante":' || COALESCE(CAST(OLD.ID_CONTA_SOLICITANTE AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_conta_solicitante":' || COALESCE(CAST(NEW.ID_CONTA_SOLICITANTE AS VARCHAR(80)), 'null');
        END
        IF (OLD.ID_USUARIO_RESPONSAVEL IS DISTINCT FROM NEW.ID_USUARIO_RESPONSAVEL) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_usuario_responsavel":' || COALESCE(CAST(OLD.ID_USUARIO_RESPONSAVEL AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_usuario_responsavel":' || COALESCE(CAST(NEW.ID_USUARIO_RESPONSAVEL AS VARCHAR(80)), 'null');
        END
        IF (OLD.ID_CONTA_PAGADOR IS DISTINCT FROM NEW.ID_CONTA_PAGADOR) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_conta_pagador":' || COALESCE(CAST(OLD.ID_CONTA_PAGADOR AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_conta_pagador":' || COALESCE(CAST(NEW.ID_CONTA_PAGADOR AS VARCHAR(80)), 'null');
        END
        IF (OLD.ID_CONTA_RECEBEDOR IS DISTINCT FROM NEW.ID_CONTA_RECEBEDOR) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"id_conta_recebedor":' || COALESCE(CAST(OLD.ID_CONTA_RECEBEDOR AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"id_conta_recebedor":' || COALESCE(CAST(NEW.ID_CONTA_RECEBEDOR AS VARCHAR(80)), 'null');
        END
        IF (OLD.VALOR IS DISTINCT FROM NEW.VALOR) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"valor":' || COALESCE(CAST(OLD.VALOR AS VARCHAR(80)), 'null');
            V_NOVO = V_NOVO || ',"valor":' || COALESCE(CAST(NEW.VALOR AS VARCHAR(80)), 'null');
        END
        IF (OLD.STATUS IS DISTINCT FROM NEW.STATUS) THEN
        BEGIN
            V_ANTES = V_ANTES || ',"status":' || COALESCE('"' || REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(CAST(OLD.STATUS AS VARCHAR(80)), ASCII_CHAR(92), ASCII_CHAR(92) || ASCII_CHAR(92)), ASCII_CHAR(34), ASCII_CHAR(92) || ASCII_CHAR(34)), ASCII_CHAR(13), ASCII_CHAR(92) || 'r'), ASCII_CHAR(10), ASCII_CHAR(92) || 'n'), ASCII_CHAR(9), ASCII_CHAR(92) || 't') || '"', 'null');
            V_NOVO = V_NOVO || ',"status":' || COALESCE('"' || REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(CAST(NEW.STATUS AS VARCHAR(80)), ASCII_CHAR(92), ASCII_CHAR(92) || ASCII_CHAR(92)), ASCII_CHAR(34), ASCII_CHAR(92) || ASCII_CHAR(34)), ASCII_CHAR(13), ASCII_CHAR(92) || 'r'), ASCII_CHAR(10), ASCII_CHAR(92) || 'n'), ASCII_CHAR(9), ASCII_CHAR(92) || 't') || '"', 'null');
        END
        IF (V_ANTES <> '') THEN
        BEGIN
            V_ANTES = '{' || SUBSTRING(V_ANTES FROM 2) || '}';
            V_NOVO = '{' || SUBSTRING(V_NOVO FROM 2) || '}';
        END
        ELSE
        BEGIN
            V_ANTES = NULL;
            V_NOVO = NULL;
        END
    END

    EXECUTE STATEMENT (
        'INSERT INTO LOG (DATA_HORA, USUARIO, TABELA, ID_REGISTRO, ACAO, VALOR_ANTERIOR, VALOR_NOVO)
         VALUES (:data_hora, :usuario, ''ESTORNO_FINANCEIRO'', :id_registro, :acao, :antes, :novo)'
    ) (
        data_hora := CURRENT_TIMESTAMP,
        usuario := COALESCE(RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_USUARIO_LOG'), RDB$GET_CONTEXT('USER_SESSION', 'ARKHE_ID_USUARIO'), CURRENT_USER),
        id_registro := CASE WHEN DELETING THEN OLD.ID_ESTORNO ELSE NEW.ID_ESTORNO END,
        acao := CASE WHEN INSERTING THEN 'INSERT' WHEN UPDATING THEN 'UPDATE' ELSE 'DELETE' END,
        antes := :V_ANTES,
        novo := :V_NOVO
    )
    ON EXTERNAL DATA SOURCE :V_DESTINO
    AS USER :V_USUARIO PASSWORD :V_SENHA
    WITH COMMON TRANSACTION;
END^

SET TERM ;^
COMMIT;