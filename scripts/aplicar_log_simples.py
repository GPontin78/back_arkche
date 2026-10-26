"""Publicar o Python antes. Sem --apply, apenas confere a instalação atual."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import config
from scripts.aplicar_log_externo import backup, comandos_sql, conectar, testar_eds
from scripts.gerar_log_simples import gerar_trigger
from scripts.gerar_migracao_log import SCHEMA, TABELAS_PRINCIPAIS, texto_sql
from scripts.unificar_log import conferir as conferir_anterior

CAMPOS_LOG = ['ID_LOG','DATA_HORA','USUARIO','TABELA','ID_REGISTRO','ACAO','VALOR_ANTERIOR','VALOR_NOVO']


def conferir(conexao):
    cursor = conexao.cursor()
    cursor.execute('SELECT ORIGEM_ID FROM CONFIGURACAO_LOG WHERE ID_CONFIGURACAO=1')
    origem = cursor.fetchone()[0]
    if not origem.endswith('-simples'):
        cursor.close()
        atuais = conferir_anterior(conexao)
        if len(atuais) != 13:
            raise RuntimeError('Aplicar a migração 013 antes da tabela simples')
        return atuais,origem
    schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
    campos = {(r[0],r[1]):r for r in schema['fields']}
    esperadas = {f'TG_AIUD_{t}_LOG':(t,114,32000,0,'AS\n'+gerar_trigger(t,campos).split('\nAS\n',1)[1].strip().removesuffix('^')) for t in TABELAS_PRINCIPAIS}
    for nome,tabela,tipo,posicao,inativo,corpo in schema['triggers']:
        if not nome.startswith('ARKHE_AUD_'):
            esperadas[nome] = (tabela,tipo,posicao,inativo,corpo)
    try:
        cursor.execute('''SELECT TRIM(RDB$TRIGGER_NAME),TRIM(RDB$RELATION_NAME),
            RDB$TRIGGER_TYPE,RDB$TRIGGER_SEQUENCE,RDB$TRIGGER_INACTIVE,RDB$TRIGGER_SOURCE
            FROM RDB$TRIGGERS WHERE COALESCE(RDB$SYSTEM_FLAG,0)=0 ORDER BY 1''')
        atuais = cursor.fetchall()
        if {r[0] for r in atuais} != set(esperadas):
            raise RuntimeError('Catálogo de triggers diferente do esperado')
        for nome,*dados in atuais:
            esperado = esperadas[nome]
            if tuple(dados[:4]) != esperado[:4] or re.sub(r'\s+',' ',dados[4]).strip() != re.sub(r'\s+',' ',esperado[4]).strip():
                raise RuntimeError(f'Trigger {nome} mudou desde o estudo')
        return atuais,origem
    finally:
        cursor.close()


def conferir_log(arquivo):
    cursor = arquivo.cursor()
    try:
        cursor.execute("SELECT TRIM(RDB$FIELD_NAME) FROM RDB$RELATION_FIELDS WHERE RDB$RELATION_NAME='LOG' ORDER BY RDB$FIELD_POSITION")
        campos = [r[0] for r in cursor.fetchall()]
        if campos and campos != CAMPOS_LOG:
            raise RuntimeError('Já existe uma LOG com estrutura diferente. Nenhuma tabela foi substituída.')
        return bool(campos)
    finally:
        cursor.close()


def aplicar(conexao,arquivo):
    _,origem = conferir(conexao)
    existe = conferir_log(arquivo)
    if origem.endswith('-simples'):
        if not existe:
            raise RuntimeError('LOG ativa não encontrada no banco separado')
        conexao.rollback()
        return False
    if not existe:
        for sql in comandos_sql((ROOT/'migrations/auditoria_separada/002_log_simples.sql').read_text(encoding='utf-8')):
            arquivo.execute_immediate(sql)
        arquivo.commit()
    cursor = conexao.cursor()
    try:
        for sql in comandos_sql((ROOT/'migrations/014_log_oito_campos.sql').read_text(encoding='utf-8')):
            cursor.execute(sql)
        # As triggers e a escolha do gravador Python mudam no mesmo commit.
        cursor.execute('UPDATE CONFIGURACAO_LOG SET ORIGEM_ID=? WHERE ID_CONFIGURACAO=1',(origem+'-simples',))
        conferir(conexao)
        testar_eds(cursor)
        conexao.commit()
        return True
    except Exception:
        conexao.rollback()
        raise
    finally:
        cursor.close()


def salvar_rollback(pasta,triggers,origem):
    sql = ['SET BAIL ON;','SET AUTODDL OFF;','SET TERM ^;']
    for nome,tabela,tipo,posicao,inativo,corpo in triggers:
        if nome.endswith('_LOG'):
            sql.append(f'CREATE OR ALTER TRIGGER {nome} FOR {tabela} ACTIVE AFTER INSERT OR UPDATE OR DELETE POSITION {posicao}\n{corpo}^')
    sql.extend(['SET TERM ;^',f'UPDATE CONFIGURACAO_LOG SET ORIGEM_ID={texto_sql(origem)} WHERE ID_CONFIGURACAO=1;','COMMIT;'])
    (pasta/'rollback-log-simples.sql').write_text('\n'.join(sql),encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    args = parser.parse_args()
    conexao = conectar(config.DB_HOST,config.DB_PORT,config.DB_NAME,config.DB_USER,config.DB_PASSWORD)
    arquivo = None
    try:
        triggers,origem = conferir(conexao)
        cursor = conexao.cursor()
        cursor.execute('SELECT DATA_SOURCE,USUARIO,SENHA FROM CONFIGURACAO_LOG WHERE ID_CONFIGURACAO=1')
        destino,usuario,senha = cursor.fetchone()
        cursor.close()
        conexao.rollback()
        servidor,nome = destino.split(':',1)
        host,porta = servidor.rsplit('/',1)
        arquivo = conectar(host,int(porta),nome,usuario,senha)
        existe = conferir_log(arquivo)
        if origem.endswith('-simples') and not existe:
            raise RuntimeError('LOG ativa não encontrada no banco separado')
        cursor = arquivo.cursor()
        cursor.execute('SELECT COUNT(*) FROM AUDITORIA_EVENTO')
        historicos = cursor.fetchone()[0]
        cursor.close()
        arquivo.rollback()
        print(f'Conferido: {len(triggers)} triggers e {historicos} logs antigos preservados.',flush=True)
        if not args.apply or origem.endswith('-simples'):
            print('LOG simples já ativa.' if origem.endswith('-simples') else 'Somente leitura.',flush=True)
            return
        sufixo = datetime.now().strftime('%Y%m%d-%H%M%S')
        pasta = ROOT/'.runtime'/('log-simples-'+sufixo)
        pasta.mkdir(parents=True,exist_ok=False)
        salvar_rollback(pasta,triggers,origem)
        backups = [backup(config.DB_HOST,config.DB_PORT,config.DB_NAME,config.DB_USER,config.DB_PASSWORD,sufixo),backup(host,int(porta),nome,usuario,senha,sufixo)]
        print('Backups concluídos:',*backups,sep='\n',flush=True)
        aplicar(conexao,arquivo)
        (pasta/'resultado.json').write_text(json.dumps({'campos':CAMPOS_LOG,'historico_antes':historicos,'backups':backups},indent=2),encoding='utf-8')
        print('Aplicado: LOG com 8 campos; 11 triggers de LOG e 2 financeiras preservadas.',flush=True)
        print('Rollback:',pasta/'rollback-log-simples.sql',flush=True)
    finally:
        conexao.close()
        if arquivo:
            arquivo.close()


if __name__ == '__main__':
    main()
