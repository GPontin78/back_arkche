"""Acrescenta IP sem apagar registros. Sem --apply, apenas confere."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config
from scripts.aplicar_log_externo import backup, comandos_sql, conectar, testar_eds
from scripts.aplicar_log_simples import CAMPOS_LOG, conferir, conferir_log, ip_ativo, salvar_rollback, sem_complementos
from scripts.gerar_migracao_log import texto_sql


def conferir_ip(arquivo):
    conferir_log(arquivo)
    cursor = arquivo.cursor()
    try:
        cursor.execute("""SELECT F.RDB$CHARACTER_LENGTH, R.RDB$NULL_FLAG
            FROM RDB$RELATION_FIELDS R JOIN RDB$FIELDS F ON F.RDB$FIELD_NAME=R.RDB$FIELD_SOURCE
            WHERE R.RDB$RELATION_NAME='LOG' AND R.RDB$FIELD_NAME='IP'""")
        campo = cursor.fetchone()
        if campo and campo != (45, None):
            raise RuntimeError('Campo IP diferente de VARCHAR(45) permitindo nulo')
        return bool(campo)
    finally:
        cursor.close()


def aplicar_ip(conexao, arquivo):
    triggers, _ = conferir(conexao)
    existe = conferir_ip(arquivo)
    if not sem_complementos(triggers):
        raise RuntimeError('Aplicar o modelo 018 antes de acrescentar o IP')
    if ip_ativo(triggers):
        if not existe:
            raise RuntimeError('Triggers de IP ativas sem o campo no banco de LOG')
        conexao.rollback()
        arquivo.rollback()
        return False
    if not existe:
        for sql in comandos_sql((ROOT/'migrations/auditoria_separada/003_log_ip.sql').read_text(encoding='utf-8')):
            arquivo.execute_immediate(sql)
        arquivo.commit()
    arquivo.rollback()
    cursor = conexao.cursor()
    try:
        cursor.execute('SELECT DATA_SOURCE,USUARIO,SENHA FROM CONFIGURACAO_LOG WHERE ID_CONFIGURACAO=1')
        destino, usuario, senha = cursor.fetchone()
        ddl = (ROOT/'migrations/019_log_ip.sql').read_text(encoding='utf-8')
        for marcador, valor in (('__LOG_DATA_SOURCE__',destino),('__LOG_USUARIO__',usuario),('__LOG_SENHA__',senha)):
            ddl = ddl.replace(texto_sql(marcador), texto_sql(valor))
        for sql in comandos_sql(ddl):
            cursor.execute(sql)
        conferir(conexao)
        testar_eds(cursor)
        conexao.commit()
        return True
    except Exception:
        conexao.rollback()
        raise
    finally:
        cursor.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    conexao = conectar(config.DB_HOST,config.DB_PORT,config.DB_NAME,config.DB_USER,config.DB_PASSWORD)
    arquivo = None
    try:
        triggers, origem = conferir(conexao)
        cursor = conexao.cursor()
        cursor.execute('SELECT DATA_SOURCE,USUARIO,SENHA FROM CONFIGURACAO_LOG WHERE ID_CONFIGURACAO=1')
        destino, usuario, senha = cursor.fetchone()
        cursor.close()
        conexao.rollback()
        servidor, nome = destino.split(':', 1)
        host, porta = servidor.rsplit('/', 1)
        arquivo = conectar(host,int(porta),nome,usuario,senha)
        existe = conferir_ip(arquivo)
        arquivo.rollback()
        if ip_ativo(triggers) and existe:
            print('Campo IP e 33 triggers já atualizados.', flush=True)
            return
        print('Conferido: 33 triggers de log; IP será acrescentado sem alterar o histórico.', flush=True)
        if not args.apply:
            return
        sufixo = datetime.now().strftime('%Y%m%d-%H%M%S')
        pasta = ROOT/'.runtime'/('log-ip-'+sufixo)
        pasta.mkdir(parents=True,exist_ok=False)
        salvar_rollback(pasta,triggers,origem)
        backups = [backup(config.DB_HOST,config.DB_PORT,config.DB_NAME,config.DB_USER,config.DB_PASSWORD,sufixo),
                   backup(host,int(porta),nome,usuario,senha,sufixo)]
        print('Backups concluídos:', *backups, sep='\n', flush=True)
        aplicar_ip(conexao,arquivo)
        (pasta/'resultado.json').write_text(json.dumps({'campos':CAMPOS_LOG+['IP'],'backups':backups,
            'triggers_log':33,'financeiras_preservadas':2},indent=2),encoding='utf-8')
        print('Aplicado: campo IP e 33 triggers; 2 financeiras e histórico preservados.', flush=True)
        print('Rollback:',pasta/'rollback-log-simples.sql',flush=True)
    finally:
        conexao.close()
        if arquivo:
            arquivo.close()


if __name__ == '__main__':
    main()
