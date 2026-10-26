"""Reduz a instalação 011 a 33 triggers. Sem --apply, somente confere.

Não altera dados, destino, credenciais, sequência ou histórico de auditoria.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
from scripts.aplicar_log_externo import backup, comandos_sql, conectar, testar_eds
from scripts.gerar_migracao_log import CAMPOS, SCHEMA, TABELAS_PRINCIPAIS, gerar_trigger


def conferir(conexao):
    schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
    campos = {(r[0], r[1]): r for r in schema['fields']}
    esperadas = {}
    for tabela in CAMPOS:
        for sigla, operacao, tipo in (('AI', 'INSERT', 2), ('AU', 'UPDATE', 4), ('AD', 'DELETE', 6)):
            corpo = 'AS\n' + gerar_trigger(tabela, operacao, campos).split('\nAS\n', 1)[1].rstrip().removesuffix('^')
            esperadas[f'TG_{sigla}_{tabela}_LOG'] = (tabela, tipo, 32000, 0, corpo)
    for nome, tabela, tipo, posicao, inativo, corpo in schema['triggers']:
        if not nome.startswith('ARKHE_AUD_'):
            esperadas[nome] = (tabela, tipo, posicao, inativo, corpo)
    cursor = conexao.cursor()
    try:
        cursor.execute('''SELECT TRIM(RDB$TRIGGER_NAME), TRIM(RDB$RELATION_NAME),
            RDB$TRIGGER_TYPE, RDB$TRIGGER_SEQUENCE, RDB$TRIGGER_INACTIVE, RDB$TRIGGER_SOURCE
            FROM RDB$TRIGGERS WHERE COALESCE(RDB$SYSTEM_FLAG,0)=0 ORDER BY 1''')
        atuais = cursor.fetchall()
        nomes = {r[0] for r in atuais}
        principais = {n for n, r in esperadas.items() if r[0] in TABELAS_PRINCIPAIS}
        if nomes not in (set(esperadas), principais):
            raise RuntimeError('Catálogo diferente da instalação estudada. Nenhuma trigger foi retirada.')
        for nome, tabela, tipo, posicao, inativo, corpo in atuais:
            esperado = esperadas[nome]
            if (tabela, tipo, posicao, inativo) != esperado[:4] or re.sub(r'\s+', ' ', corpo).strip() != re.sub(r'\s+', ' ', esperado[4]).strip():
                raise RuntimeError(f'Trigger {nome} mudou desde o estudo. Revise antes de aplicar.')
        return atuais
    finally:
        cursor.close()


def aplicar(conexao):
    atuais = conferir(conexao)
    if len(atuais) == 35:
        conexao.rollback()
        return False
    cursor = conexao.cursor()
    try:
        testar_eds(cursor)
        for comando in comandos_sql((ROOT / 'migrations/012_log_tabelas_principais.sql').read_text(encoding='utf-8')):
            cursor.execute(comando)
        if len(conferir(conexao)) != 35:
            raise RuntimeError('Quantidade de triggers inesperada')
        conexao.commit()
        return True
    except Exception:
        conexao.rollback()
        raise
    finally:
        cursor.close()


def salvar_rollback(pasta, atuais):
    sql = ['SET BAIL ON;', 'SET AUTODDL OFF;', 'SET TERM ^;']
    for nome, tabela, tipo, posicao, inativo, corpo in atuais:
        if tabela in TABELAS_PRINCIPAIS:
            continue
        operacao = {2:'INSERT', 4:'UPDATE', 6:'DELETE'}[tipo]
        sql.append(f'CREATE OR ALTER TRIGGER {nome} FOR {tabela} ACTIVE AFTER {operacao} POSITION {posicao}\n{corpo}^')
        sql.append(f'GRANT SELECT ON CONFIGURACAO_LOG TO TRIGGER {nome}^')
        sql.append(f'GRANT USAGE ON SEQUENCE GEN_LOG_EVENTO TO TRIGGER {nome}^')
        for origem in {'FATURA_COMPRA': ('CARTAO','COMPRA'), 'MAURO_MENSAGEM': ('MAURO_CONVERSA',)}.get(tabela, ()):
            sql.append(f'GRANT SELECT ON {origem} TO TRIGGER {nome}^')
    sql.extend(['SET TERM ;^', 'COMMIT;'])
    (pasta / 'rollback-reducao.sql').write_text('\n'.join(sql), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    conexao = conectar(config.DB_HOST, config.DB_PORT, config.DB_NAME, config.DB_USER, config.DB_PASSWORD)
    try:
        atuais = conferir(conexao)
        conexao.rollback()
        print(f'Conferido: {len(atuais)} triggers. Destino: 33 de LOG + 2 financeiras.', flush=True)
        if not args.apply or len(atuais) == 35:
            return
        # O destino efetivo vem da configuração privada já usada pelas triggers.
        cursor = conexao.cursor()
        cursor.execute('SELECT DATA_SOURCE, USUARIO, SENHA FROM CONFIGURACAO_LOG WHERE ID_CONFIGURACAO=1')
        destino, usuario, senha = cursor.fetchone()
        cursor.close()
        conexao.rollback()
        servidor, nome_audit = destino.split(':', 1)
        host_audit, porta_audit = servidor.rsplit('/', 1)
        sufixo = datetime.now().strftime('%Y%m%d-%H%M%S')
        pasta = ROOT / '.runtime' / ('log-principais-' + sufixo)
        pasta.mkdir(parents=True, exist_ok=False)
        salvar_rollback(pasta, atuais)
        backups = [backup(config.DB_HOST, config.DB_PORT, config.DB_NAME, config.DB_USER, config.DB_PASSWORD, sufixo),
                   backup(host_audit, int(porta_audit), nome_audit, usuario, senha, sufixo)]
        print('Backups concluídos:', *backups, sep='\n', flush=True)
        aplicar(conexao)
        (pasta / 'resultado.json').write_text(json.dumps({'triggers_log':33,
            'triggers_financeiras':2, 'backups':backups}, indent=2), encoding='utf-8')
        print('Aplicado: 33 triggers de LOG, 11 tabelas principais, 2 financeiras preservadas.', flush=True)
        print('Rollback:', pasta / 'rollback-reducao.sql', flush=True)
    finally:
        conexao.close()


if __name__ == '__main__':
    main()
