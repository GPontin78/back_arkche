"""Confere o esquema; --apply faz backup e acrescenta as tabelas do MAURO."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config
from scripts.aplicar_log_externo import backup, comandos_sql, conectar


TABELAS = ('MAURO_CADASTRO_PROPOSTA', 'MAURO_CADASTRO_PIN_TENTATIVA', 'MAURO_ADMIN_MENSAGEM')
COLUNAS = {
    TABELAS[0]: {'ID_PROPOSTA','ID_CONVERSA','ID_USUARIO','ID_CONTA','ACAO','DADOS','STATUS',
                 'ID_REGISTRO','CRIADA_EM','EXPIRA_EM','CONFIRMADA_EM','RESULTADO'},
    TABELAS[1]: {'ID_TENTATIVA','ID_PROPOSTA','ID_USUARIO','VALIDO','CRIADA_EM'},
    TABELAS[2]: {'ID_MENSAGEM','ID_USUARIO','PAPEL','CONTEUDO','CRIADA_EM'},
}


def tabelas_instaladas(conexao):
    cursor = conexao.cursor()
    try:
        cursor.execute("SELECT TRIM(RDB$RELATION_NAME) FROM RDB$RELATIONS WHERE COALESCE(RDB$SYSTEM_FLAG,0)=0")
        existentes = {r[0] for r in cursor.fetchall()}
        return [t for t in TABELAS if t in existentes]
    finally:
        cursor.close()


def aplicar(conexao):
    existentes = tabelas_instaladas(conexao)
    if existentes == list(TABELAS):
        cursor = conexao.cursor()
        try:
            for tabela in TABELAS:
                cursor.execute('SELECT TRIM(RDB$FIELD_NAME) FROM RDB$RELATION_FIELDS WHERE RDB$RELATION_NAME = ?', (tabela,))
                if {r[0] for r in cursor.fetchall()} != COLUNAS[tabela]:
                    raise RuntimeError('Estrutura diferente da migração 020: ' + tabela)
        finally:
            cursor.close()
        return False
    if existentes:
        raise RuntimeError('A migração está incompleta. Confira o catálogo antes de continuar.')
    try:
        for sql in comandos_sql((ROOT / 'migrations/020_mauro_cadastros_contexto.sql').read_text(encoding='utf-8')):
            conexao.execute_immediate(sql)
        if tabelas_instaladas(conexao) != list(TABELAS):
            raise RuntimeError('A migração não criou as três tabelas esperadas.')
        conexao.commit()
        return True
    except Exception:
        conexao.rollback()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    argumentos = parser.parse_args()
    conexao = conectar(config.DB_HOST, config.DB_PORT, config.DB_NAME, config.DB_USER, config.DB_PASSWORD)
    try:
        instaladas = tabelas_instaladas(conexao)
        print('Tabelas instaladas:', len(instaladas), 'de', len(TABELAS), flush=True)
        if not argumentos.apply or len(instaladas) == len(TABELAS):
            return
        cursor = conexao.cursor()
        cursor.execute("SELECT TRIM(RDB$TRIGGER_NAME), RDB$TRIGGER_SOURCE FROM RDB$TRIGGERS WHERE COALESCE(RDB$SYSTEM_FLAG,0)=0 ORDER BY 1")
        triggers = cursor.fetchall()
        antes = hashlib.sha256(repr(triggers).encode()).hexdigest()
        cursor.close()
        conexao.rollback()
        sufixo = 'antes-mauro-completo-' + datetime.now().strftime('%Y%m%d-%H%M%S')
        arquivo_backup = backup(config.DB_HOST, config.DB_PORT, config.DB_NAME, config.DB_USER, config.DB_PASSWORD, sufixo)
        aplicar(conexao)
        cursor = conexao.cursor()
        cursor.execute("SELECT TRIM(RDB$TRIGGER_NAME), RDB$TRIGGER_SOURCE FROM RDB$TRIGGERS WHERE COALESCE(RDB$SYSTEM_FLAG,0)=0 ORDER BY 1")
        depois = hashlib.sha256(repr(cursor.fetchall()).encode()).hexdigest()
        cursor.close()
        if antes != depois:
            raise RuntimeError('As fontes das triggers devem permanecer iguais.')
        pasta = ROOT / '.runtime' / sufixo
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / 'migracao.json').write_text(json.dumps({'backup': arquivo_backup, 'tabelas': list(TABELAS),
            'triggers_preservadas_sha256': depois, 'alteracao_em_dados_antigos': False}, indent=2), encoding='utf-8')
        print('Migração 020 aplicada. Backup concluído; triggers e dados antigos preservados.', flush=True)
    finally:
        conexao.close()


if __name__ == '__main__':
    main()
