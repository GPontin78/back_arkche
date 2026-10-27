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
from scripts.gerar_log_texto import gerar_trigger as gerar_trigger_texto
from scripts.gerar_log_tres_triggers import OPERACOES, gerar_trigger as gerar_trigger_separada
from scripts.gerar_log_modelo import gerar_trigger as gerar_trigger_modelo
from scripts.gerar_migracao_log import SCHEMA, TABELAS_PRINCIPAIS, texto_sql
from scripts.unificar_log import conferir as conferir_anterior

CAMPOS_LOG = ['ID_LOG','DATA_HORA','USUARIO','TABELA','ID_REGISTRO','ACAO','VALOR_ANTERIOR','VALOR_NOVO']


def fonte_texto(tabela):
    return 'AS\n'+gerar_trigger_texto(tabela).split('\nAS\n',1)[1].strip().removesuffix('^')


def texto_ativo(triggers):
    if tres_ativas(triggers):
        return True
    usuario = next(r for r in triggers if r[0]=='TG_AIUD_USUARIO_LOG')
    return re.sub(r'\s+',' ',usuario[5]).strip()==re.sub(r'\s+',' ',fonte_texto('USUARIO')).strip()


def tres_ativas(triggers):
    nomes = {f'TG_{sigla}_{tabela}_LOG' for tabela in TABELAS_PRINCIPAIS for sigla,_,_ in OPERACOES}
    return {r[0] for r in triggers if r[0].endswith('_LOG')} == nomes


def modelo_ativo(triggers):
    return any(r[0]=='TG_AU_USUARIO_LOG' and 'DECLARE VARIABLE V_ANTIGO VARCHAR(2000);' in r[5] for r in triggers)


def sem_complementos(triggers):
    return modelo_ativo(triggers) and all(r[3]==0 and 'WITH COMMON TRANSACTION' not in r[5].upper()
                                        for r in triggers if r[0].endswith('_LOG'))


def conferir(conexao):
    cursor = conexao.cursor()
    cursor.execute('SELECT ORIGEM_ID,DATA_SOURCE,USUARIO,SENHA FROM CONFIGURACAO_LOG WHERE ID_CONFIGURACAO=1')
    origem,destino,usuario,senha = cursor.fetchone()
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
    separadas = {nome:dados for nome,dados in esperadas.items() if not nome.endswith('_LOG')}
    modelo = dict(separadas)
    modelo_anterior = dict(separadas)
    for tabela in TABELAS_PRINCIPAIS:
        for sigla,operacao,tipo in OPERACOES:
            corpo = 'AS\n'+gerar_trigger_separada(tabela,operacao).split('\nAS\n',1)[1].strip().removesuffix('^')
            separadas[f'TG_{sigla}_{tabela}_LOG'] = (tabela,tipo,32000,0,corpo)
            corpo_modelo = 'AS\n'+gerar_trigger_modelo(tabela,operacao,destino,usuario,senha).split('\nAS\n',1)[1].strip().removesuffix('^')
            modelo[f'TG_{sigla}_{tabela}_LOG'] = (tabela,tipo,0,0,corpo_modelo)
            corpo_anterior = 'AS\n'+gerar_trigger_modelo(tabela,operacao,destino,usuario,senha,sem_complementos=False).split('\nAS\n',1)[1].strip().removesuffix('^')
            modelo_anterior[f'TG_{sigla}_{tabela}_LOG'] = (tabela,tipo,32000,0,corpo_anterior)
    try:
        cursor.execute('''SELECT TRIM(RDB$TRIGGER_NAME),TRIM(RDB$RELATION_NAME),
            RDB$TRIGGER_TYPE,RDB$TRIGGER_SEQUENCE,RDB$TRIGGER_INACTIVE,RDB$TRIGGER_SOURCE
            FROM RDB$TRIGGERS WHERE COALESCE(RDB$SYSTEM_FLAG,0)=0 ORDER BY 1''')
        atuais = cursor.fetchall()
        if {r[0] for r in atuais} == set(separadas):
            esperadas_tres = modelo if modelo_ativo(atuais) else separadas
            if modelo_ativo(atuais) and not sem_complementos(atuais):
                esperadas_tres = modelo_anterior
            for nome,*dados in atuais:
                esperado = esperadas_tres[nome]
                if tuple(dados[:4]) != esperado[:4] or re.sub(r'\s+',' ',dados[4]).strip() != re.sub(r'\s+',' ',esperado[4]).strip():
                    raise RuntimeError(f'Trigger {nome} mudou desde o estudo')
            return atuais,origem
        if {r[0] for r in atuais} != set(esperadas):
            raise RuntimeError('Catálogo de triggers diferente do esperado')
        versao_json = versao_texto = True
        for nome,*dados in atuais:
            esperado = esperadas[nome]
            if tuple(dados[:4]) != esperado[:4]:
                raise RuntimeError(f'Trigger {nome} mudou desde o estudo')
            corpo = re.sub(r'\s+',' ',dados[4]).strip()
            versao_json = versao_json and corpo == re.sub(r'\s+',' ',esperado[4]).strip()
            novo = fonte_texto(dados[0]) if nome.endswith('_LOG') else esperado[4]
            versao_texto = versao_texto and corpo == re.sub(r'\s+',' ',novo).strip()
        if not versao_json and not versao_texto:
            raise RuntimeError('As fontes das triggers mudaram desde o estudo')
        return atuais,origem
    finally:
        cursor.close()


def conferir_log(arquivo):
    cursor = arquivo.cursor()
    try:
        cursor.execute("""SELECT TRIM(R.RDB$FIELD_NAME),F.RDB$FIELD_TYPE,R.RDB$IDENTITY_TYPE
            FROM RDB$RELATION_FIELDS R JOIN RDB$FIELDS F ON F.RDB$FIELD_NAME=R.RDB$FIELD_SOURCE
            WHERE R.RDB$RELATION_NAME='LOG' ORDER BY R.RDB$FIELD_POSITION""")
        definicoes = cursor.fetchall()
        campos = [r[0] for r in definicoes]
        if campos and campos != CAMPOS_LOG:
            raise RuntimeError('Já existe uma LOG com estrutura diferente. Nenhuma tabela foi substituída.')
        if campos and ([r[1] for r in definicoes] != [16,35,37,37,16,37,261,261] or definicoes[0][2] != 1):
            raise RuntimeError('Tipos ou identidade da LOG diferentes da estrutura estudada')
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


def salvar_rollback(pasta,triggers,origem,remover_tres=False):
    sql = ['SET BAIL ON;','SET AUTODDL OFF;','SET TERM ^;']
    if remover_tres:
        for tabela in TABELAS_PRINCIPAIS:
            sql.extend(f'DROP TRIGGER TG_{sigla}_{tabela}_LOG^' for sigla,_,_ in OPERACOES)
    for nome,tabela,tipo,posicao,inativo,corpo in triggers:
        if nome.endswith('_LOG'):
            evento = {2:'INSERT',4:'UPDATE',6:'DELETE',114:'INSERT OR UPDATE OR DELETE'}[tipo]
            estado = 'INACTIVE' if inativo else 'ACTIVE'
            sql.append(f'CREATE OR ALTER TRIGGER {nome} FOR {tabela} {estado} AFTER {evento} POSITION {posicao}\n{corpo}^')
    sql.extend(['SET TERM ;^',f'UPDATE CONFIGURACAO_LOG SET ORIGEM_ID={texto_sql(origem)} WHERE ID_CONFIGURACAO=1;','COMMIT;'])
    (pasta/'rollback-log-simples.sql').write_text('\n'.join(sql),encoding='utf-8')


def aplicar_texto(conexao,arquivo):
    atuais,origem = conferir(conexao)
    if not origem.endswith('-simples') or not conferir_log(arquivo):
        raise RuntimeError('Aplicar a LOG de oito campos antes das triggers em texto')
    if texto_ativo(atuais):
        conexao.rollback()
        return False
    cursor = conexao.cursor()
    try:
        for sql in comandos_sql((ROOT/'migrations/015_log_texto_simples.sql').read_text(encoding='utf-8')):
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


def aplicar_tres(conexao,arquivo):
    atuais,origem = conferir(conexao)
    if not origem.endswith('-simples') or not conferir_log(arquivo):
        raise RuntimeError('Aplicar a LOG de oito campos antes das três triggers')
    if tres_ativas(atuais):
        conexao.rollback()
        return False
    cursor = conexao.cursor()
    try:
        for sql in comandos_sql((ROOT/'migrations/016_log_tres_triggers.sql').read_text(encoding='utf-8')):
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


def aplicar_modelo(conexao,arquivo):
    atuais,origem = conferir(conexao)
    if not origem.endswith('-simples') or not tres_ativas(atuais) or not conferir_log(arquivo):
        raise RuntimeError('Aplicar a LOG de oito campos com três triggers antes do modelo direto')
    if sem_complementos(atuais):
        conexao.rollback()
        return False
    cursor = conexao.cursor()
    try:
        cursor.execute('SELECT DATA_SOURCE,USUARIO,SENHA FROM CONFIGURACAO_LOG WHERE ID_CONFIGURACAO=1')
        destino,usuario,senha = cursor.fetchone()
        ddl = (ROOT/'migrations/018_log_sem_complementos.sql').read_text(encoding='utf-8')
        for marcador,valor in (('__LOG_DATA_SOURCE__',destino),('__LOG_USUARIO__',usuario),('__LOG_SENHA__',senha)):
            ddl = ddl.replace(texto_sql(marcador),texto_sql(valor))
        for sql in comandos_sql(ddl):
            cursor.execute(sql)
        # Omitir POSITION em CREATE OR ALTER mantém a posição antiga.
        # Volta ao padrão sem recriar triggers nem perder privilégios/descrições.
        for tabela in TABELAS_PRINCIPAIS:
            for sigla,_,_ in OPERACOES:
                cursor.execute(f'ALTER TRIGGER TG_{sigla}_{tabela}_LOG POSITION 0')
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
    parser.add_argument('--apply',action='store_true')
    versao = parser.add_mutually_exclusive_group()
    versao.add_argument('--texto',action='store_true',help='Usa resumos em texto, sem JSON')
    versao.add_argument('--tres',action='store_true',help='Separa INSERT, UPDATE e DELETE: três triggers por tabela')
    versao.add_argument('--modelo',action='store_true',help='Usa variáveis antigo/novo e parâmetros posicionais, como no exemplo')
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
        atualizado = origem.endswith('-simples') and (not args.texto or texto_ativo(triggers))
        if args.tres:
            atualizado = origem.endswith('-simples') and tres_ativas(triggers)
        if args.modelo:
            atualizado = origem.endswith('-simples') and sem_complementos(triggers)
        if not args.apply or atualizado:
            print('Versão solicitada já ativa.' if atualizado else 'Somente leitura.',flush=True)
            return
        sufixo = datetime.now().strftime('%Y%m%d-%H%M%S')
        prefixo = 'log-modelo-' if args.modelo else 'log-tres-' if args.tres else 'log-texto-' if args.texto else 'log-simples-'
        pasta = ROOT/'.runtime'/(prefixo+sufixo)
        pasta.mkdir(parents=True,exist_ok=False)
        salvar_rollback(pasta,triggers,origem,remover_tres=args.tres)
        backups = [backup(config.DB_HOST,config.DB_PORT,config.DB_NAME,config.DB_USER,config.DB_PASSWORD,sufixo),backup(host,int(porta),nome,usuario,senha,sufixo)]
        print('Backups concluídos:',*backups,sep='\n',flush=True)
        if args.modelo:
            aplicar_modelo(conexao,arquivo)
        elif args.tres:
            aplicar_tres(conexao,arquivo)
        elif args.texto:
            aplicar_texto(conexao,arquivo)
        else:
            aplicar(conexao,arquivo)
        (pasta/'resultado.json').write_text(json.dumps({'campos':CAMPOS_LOG,'historico_antes':historicos,'backups':backups,'texto':args.texto or args.tres or args.modelo,'tres_por_tabela':args.tres or args.modelo,'modelo_direto':args.modelo},indent=2),encoding='utf-8')
        quantidade = 33 if args.tres or args.modelo else 11
        print(f'Aplicado: LOG com 8 campos; {quantidade} triggers de LOG e 2 financeiras preservadas.',flush=True)
        print('Rollback:',pasta/'rollback-log-simples.sql',flush=True)
    finally:
        conexao.close()
        if arquivo:
            arquivo.close()


if __name__ == '__main__':
    main()
