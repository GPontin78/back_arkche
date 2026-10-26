"""Conferência somente leitura; --apply faz backup e troca o DDL em um commit.

Usa a configuração atual do backend. Nunca imprime credenciais e nunca executa
operações financeiras. Publicar primeiro auditoria.py/assistente_mauro.py/mauro_pix.py.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys

import fdb
import fdb.services


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config


def comandos_sql(texto):
    texto = re.sub(r'/\*.*?\*/', '', texto, flags=re.S)
    terminador = ';'
    acumulado = ''
    for linha in texto.splitlines():
        if not acumulado.strip() and linha.strip().upper().startswith('SET TERM '):
            novo = linha.split()[2]
            terminador = novo[:-len(terminador)] if novo.endswith(terminador) else novo
            continue
        acumulado += linha + '\n'
        if acumulado.rstrip().endswith(terminador):
            comando = acumulado.rstrip()[:-len(terminador)].strip()
            acumulado = ''
            if comando and not comando.upper().startswith(('SET BAIL ', 'SET AUTODDL ', 'COMMIT')):
                yield comando
    if acumulado.strip():
        raise ValueError('SQL incompleto; nenhum commit foi efetuado')


def conectar(host, porta, nome, usuario, senha):
    return fdb.connect(host=host, port=int(porta), database=nome,
        user=usuario, password=senha, charset='UTF8')


def conferir_principal(conexao, esperado):
    transacao = conexao.trans(fdb.ISOLATION_LEVEL_READ_COMMITED_RO)
    cursor = transacao.cursor()
    try:
        cursor.execute('''SELECT TRIM(RDB$TRIGGER_NAME), TRIM(RDB$RELATION_NAME),
            RDB$TRIGGER_TYPE, RDB$TRIGGER_SEQUENCE, RDB$TRIGGER_INACTIVE, RDB$TRIGGER_SOURCE
            FROM RDB$TRIGGERS WHERE COALESCE(RDB$SYSTEM_FLAG,0)=0 ORDER BY 1''')
        atuais = cursor.fetchall()
        normalizar = lambda linhas: [(r[0],r[1],r[2],r[3],r[4],r[5].replace('\r','').strip()) for r in linhas]
        if normalizar(atuais) != normalizar(esperado['triggers']):
            raise RuntimeError('As triggers mudaram desde o estudo. Refaça a comparação antes de aplicar.')
        cursor.execute('''SELECT TRIM(RF.RDB$RELATION_NAME), TRIM(RF.RDB$FIELD_NAME),
            F.RDB$FIELD_TYPE, F.RDB$FIELD_SUB_TYPE, F.RDB$FIELD_LENGTH, F.RDB$FIELD_SCALE,
            RF.RDB$DEFAULT_SOURCE, RF.RDB$NULL_FLAG
            FROM RDB$RELATION_FIELDS RF JOIN RDB$FIELDS F ON F.RDB$FIELD_NAME=RF.RDB$FIELD_SOURCE
            JOIN RDB$RELATIONS R ON R.RDB$RELATION_NAME=RF.RDB$RELATION_NAME
            WHERE COALESCE(R.RDB$SYSTEM_FLAG,0)=0 ORDER BY 1,RF.RDB$FIELD_POSITION''')
        if [list(r) for r in cursor.fetchall()] != esperado['fields']:
            raise RuntimeError('O schema mudou desde o estudo. Migração não aplicada.')
        cursor.execute('SELECT TRIM(RDB$PROCEDURE_NAME), RDB$PROCEDURE_SOURCE FROM RDB$PROCEDURES WHERE COALESCE(RDB$SYSTEM_FLAG,0)=0 ORDER BY 1')
        if [(r[0], r[1].replace('\r','').strip()) for r in cursor.fetchall()] != [(r[0], r[1].replace('\r','').strip()) for r in esperado['procedures']]:
            raise RuntimeError('As procedures mudaram desde o estudo. Migração não aplicada.')
        cursor.execute('SELECT COUNT(*) FROM AUDITORIA_EVENTO_OUTBOX WHERE AUDITADO_EM IS NULL')
        pendentes = int(cursor.fetchone()[0])
        return atuais, pendentes
    finally:
        cursor.close()
        transacao.rollback()


def backup(host, porta, nome, usuario, senha, sufixo):
    destino = str(Path(nome).with_name(Path(nome).stem + '-antes-log-' + sufixo + '.fbk'))
    servico = fdb.services.connect(host=f'{host}/{porta}:service_mgr', user=usuario, password=senha)
    try:
        servico.backup(nome, destino, collect_garbage=0)
        servico.wait()
    finally:
        servico.close()
    return destino


def testar_eds(cursor):
    cursor.execute('''EXECUTE BLOCK RETURNS (OK INTEGER) AS
        DECLARE VARIABLE V_DESTINO VARCHAR(512);
        DECLARE VARIABLE V_USUARIO VARCHAR(63);
        DECLARE VARIABLE V_SENHA VARCHAR(255);
        BEGIN
            SELECT DATA_SOURCE, USUARIO, SENHA FROM CONFIGURACAO_LOG
            WHERE ID_CONFIGURACAO=1 INTO :V_DESTINO, :V_USUARIO, :V_SENHA;
            EXECUTE STATEMENT 'SELECT COUNT(*) FROM RDB$DATABASE'
            ON EXTERNAL DATA SOURCE :V_DESTINO AS USER :V_USUARIO PASSWORD :V_SENHA
            WITH COMMON TRANSACTION INTO :OK;
            SUSPEND;
        END''')
    if cursor.fetchone() != (1,):
        raise RuntimeError('A conexão EDS não foi validada')


def aplicar_ddl(conexao, destino, usuario, senha, origem):
    cursor = conexao.cursor()
    estruturas_criadas = False
    try:
        comandos = list(comandos_sql((ROOT / 'migrations/011_log_externo_padronizado.sql').read_text(encoding='utf-8')))
        # Firebird exige que a tabela esteja confirmada antes de preparar DML.
        # Esta etapa é aditiva; as triggers antigas continuam ativas.
        for comando in comandos[:3]:
            cursor.execute(comando)
        conexao.commit()
        estruturas_criadas = True
        cursor.execute('INSERT INTO CONFIGURACAO_LOG VALUES (1, ?, ?, ?, ?)',
            (destino, usuario, senha, origem + '-log-v2'))
        for comando in comandos[3:]:
            cursor.execute(comando)
        for comando in comandos_sql((ROOT / 'migrations/012_log_tabelas_principais.sql').read_text(encoding='utf-8')):
            cursor.execute(comando)
        testar_eds(cursor)
        cursor.execute("SELECT COUNT(*) FROM RDB$TRIGGERS WHERE COALESCE(RDB$SYSTEM_FLAG,0)=0")
        if cursor.fetchone() != (35,):
            raise RuntimeError('Quantidade inesperada de triggers. Migração revertida.')
        conexao.commit()
    except Exception:
        conexao.rollback()
        if estruturas_criadas:
            cursor.execute('DROP TABLE CONFIGURACAO_LOG')
            cursor.execute('DROP SEQUENCE GEN_LOG_EVENTO')
            cursor.execute('DROP EXCEPTION EX_LOG_CONFIGURACAO')
            conexao.commit()
        raise
    finally:
        cursor.close()


def salvar_rollback(pasta, triggers):
    texto = ['/* Restaurar primeiro o backend anterior. Não remove logs históricos. */',
             'SET BAIL ON;', 'SET AUTODDL OFF;', 'SET TERM ^;']
    from scripts.gerar_migracao_log import CAMPOS
    for tabela in CAMPOS:
        for sigla in ('AI','AU','AD'):
            texto.append(f'DROP TRIGGER TG_{sigla}_{tabela}_LOG^')
    antigo = (ROOT / 'migrations/007_auditoria_outbox_triggers.sql').read_text(encoding='utf-8')
    procedure = antigo.split('CREATE OR ALTER PROCEDURE ',1)[1].split('END^',1)[0]
    texto.append('CREATE OR ALTER PROCEDURE ' + procedure + 'END^')
    for nome, tabela, tipo, posicao, inativo, corpo in triggers:
        evento = {2:'INSERT',4:'UPDATE',6:'DELETE'}[tipo]
        estado = 'INACTIVE' if inativo else 'ACTIVE'
        texto.append(f'CREATE OR ALTER TRIGGER {nome} FOR {tabela} {estado} AFTER {evento} POSITION {posicao} {corpo}^')
    texto.extend(['DROP TABLE CONFIGURACAO_LOG^', 'DROP SEQUENCE GEN_LOG_EVENTO^',
                  'DROP EXCEPTION EX_LOG_CONFIGURACAO^', 'SET TERM ;^', 'COMMIT;'])
    (pasta / 'rollback-triggers.sql').write_text('\n'.join(texto), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    argumentos = parser.parse_args()
    nome_audit = os.environ['ARKHE_AUDIT_DB_NAME']
    host_audit = os.getenv('ARKHE_AUDIT_DB_HOST', config.DB_HOST)
    porta_audit = int(os.getenv('ARKHE_AUDIT_DB_PORT', str(config.DB_PORT)))
    usuario_audit = os.getenv('ARKHE_AUDIT_DB_USER', config.DB_USER)
    senha_audit = os.getenv('ARKHE_AUDIT_DB_PASSWORD', config.DB_PASSWORD)
    destino = os.getenv('ARKHE_AUDIT_DATA_SOURCE') or f'{host_audit}/{porta_audit}:{nome_audit}'
    if (host_audit, porta_audit, nome_audit) == (config.DB_HOST, config.DB_PORT, config.DB_NAME):
        raise RuntimeError('O banco de LOG deve ser separado do banco principal')
    esperado = json.loads((ROOT / 'tests/fixtures/log_schema_online_20261026.json').read_text(encoding='utf-8'))
    conexao = conectar(config.DB_HOST, config.DB_PORT, config.DB_NAME, config.DB_USER, config.DB_PASSWORD)
    arquivo = conectar(host_audit, porta_audit, nome_audit, usuario_audit, senha_audit)
    try:
        triggers, pendentes = conferir_principal(conexao, esperado)
        transacao = arquivo.trans(fdb.ISOLATION_LEVEL_READ_COMMITED_RO)
        cursor = transacao.cursor()
        cursor.execute('SELECT COUNT(*) FROM AUDITORIA_EVENTO')
        total_antes = int(cursor.fetchone()[0])
        cursor.close()
        transacao.rollback()
        print(f'Conferido: {len(triggers)} triggers, {total_antes} logs históricos, {pendentes} eventos antigos pendentes.', flush=True)
        if not argumentos.apply:
            print('Somente leitura. Nenhuma alteração aplicada.')
            return

        sufixo = datetime.now().strftime('%Y%m%d-%H%M%S')
        pasta = ROOT / '.runtime' / ('log-' + sufixo)
        pasta.mkdir(parents=True, exist_ok=False)
        salvar_rollback(pasta, triggers)
        backups = [backup(config.DB_HOST, config.DB_PORT, config.DB_NAME, config.DB_USER, config.DB_PASSWORD, sufixo),
                   backup(host_audit, porta_audit, nome_audit, usuario_audit, senha_audit, sufixo)]
        print('Backups Firebird concluídos:', *backups, sep='\n', flush=True)
        base = f'{config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}'
        origem = os.getenv('ARKHE_AUDIT_SOURCE_ID') or ('arkhe-' + hashlib.sha256(base.encode('utf-8')).hexdigest()[:24])
        # Reconfere após o backup para não sobrescrever uma alteração concorrente.
        conferir_principal(conexao, esperado)
        aplicar_ddl(conexao, destino, usuario_audit, senha_audit, origem)
        (pasta / 'resultado.json').write_text(json.dumps({
            'triggers_log':33, 'triggers_financeiras':2, 'backups':backups,
            'historico_antes':total_antes, 'pendentes_antigos':pendentes,
        }, indent=2), encoding='utf-8')
        print('Aplicado: 33 triggers de LOG e 2 regras financeiras preservadas; EDS validado por leitura.')
        print('Rollback do DDL:', pasta / 'rollback-triggers.sql')
    finally:
        conexao.close()
        arquivo.close()


if __name__ == '__main__':
    main()
