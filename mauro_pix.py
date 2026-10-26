"""Fluxo de propostas Pix do MAURO. O modelo nunca decide nem executa a operação."""
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from flask import current_app, jsonify, request

from auditoria import registrar_evento_flask
from banco import con
from funcao import data_atual, verificar_pin_usuario
from notificacoes import tentar_publicar_eventos
from operacoes_financeiras import (
    COLUNAS_PIX,
    ErroOperacaoFinanceira,
    _normalizar_chave,
    _valor_monetario_api,
    executar_pix_para_conta,
    hash_chave_pix,
)


VALOR_RE = re.compile(
    r"(?i)R\$\s*((?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2}|\.\d{1,2})?)(?![\d.,])"
)
VALOR_REAIS_RE = re.compile(
    r"(?i)\b((?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2}|\.\d{1,2})?)(?![\d.,])\s*(?:reais?|reias|brl)\b"
)
EMAIL_RE = re.compile(r"(?i)(?<![\w.+-])[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9-]+(?:\.[A-Z0-9-]+)+")
UUID_RE = re.compile(r"(?i)(?<![\w])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![\w])")
TOKEN_PIX_RE = re.compile(r"(?i)(?<![\w])[a-f0-9]{32,64}(?![\w])")
NUMERO_RE = re.compile(r"(?<!\d)(?:\+?\d[\d().\s-]{8,}\d)(?!\d)")
CHAVE_TIPO_RE = re.compile(r"(?i)\b(cpf|cnpj|telefone|celular|e-?mail|chave aleat[oó]ria)\b")
PALAVRAS_ALVO_PROPRIO = re.compile(r"(?i)\b(minha|minhas|pr[oó]pria|pr[oó]prio|outra|segunda)\b.*\b(conta|contas)\b|\b(conta|contas)\b.*\b(minha|minhas|pr[oó]pria|pr[oó]prio|outra|segunda)\b")
TIPO_DESTINO_CHAVE = 'CHAVE'
TIPO_DESTINO_CONTA = 'CONTA'
EXPIRACAO_COLETA_MINUTOS = 15
EXPIRACAO_PROPOSTA_MINUTOS = 5
LIMITE_TENTATIVAS_PIN = 5
JANELA_TENTATIVAS_PIN_MINUTOS = 15

COLUNAS_POR_TIPO = {
    'email': COLUNAS_PIX['email'],
    'telefone': COLUNAS_PIX['telefone'],
    'cpf': COLUNAS_PIX['cpf'],
    'cnpj': COLUNAS_PIX['cnpj'],
    'aleatoria': COLUNAS_PIX['aleatoria'],
}


def extrair_valor(texto):
    """Lê um valor explicitamente informado, sem usar o modelo ou inferir um padrão."""
    texto = str(texto or '')
    encontrado = VALOR_RE.search(texto) or VALOR_REAIS_RE.search(texto)
    if not encontrado:
        # Em uma resposta curta a uma pergunta do MAURO, um valor isolado é inequívoco.
        encontrado = re.fullmatch(r"\s*(\d{1,10}(?:[,.]\d{1,2})?)\s*", texto)
    if not encontrado:
        # Também permite “transfira 20 para ...”, mas não captura números de uma chave.
        encontrado = re.search(
            r"(?i)\b(?:pix|transfer\w*|transfir\w*|mand\w*|envi\w*)\s+(?:de\s+)?"
            r"(\d{1,10}(?:[,.]\d{1,2})?)(?![\d.,])\s+(?:para|pra)\b", texto,
        )
    if not encontrado:
        # Só captura número sem unidade quando ele é explicitamente apresentado
        # como valor de Pix; nunca interpreta CPF/chave isolada como quantia.
        encontrado = re.search(
            r"(?i)\bpix\s+(?:de\s+|no\s+valor\s+de\s+|valor\s+de\s+)"
            r"(\d{1,10}(?:[,.]\d{1,2})?)(?![\d.,])\b",
            texto,
        )
    if not encontrado:
        return None, None
    bruto = encontrado.group(1)
    if ',' in bruto:
        normalizado = bruto.replace('.', '').replace(',', '.')
    elif re.fullmatch(r'\d{1,3}(?:\.\d{3})+', bruto):
        normalizado = bruto.replace('.', '')
    elif bruto.count('.') > 1:
        normalizado = bruto.replace('.', '')
    else:
        normalizado = bruto
    try:
        valor = _valor_monetario_api(Decimal(normalizado))
    except (InvalidOperation, TypeError, ValueError):
        valor = None
    if valor is None:
        return None, (encontrado.start(1), encontrado.end(1))
    return valor, (encontrado.start(1), encontrado.end(1))


def extrair_chave(texto, faixa_valor=None):
    """Extrai uma chave Pix da mensagem. Chaves nunca são passadas ao Gemini."""
    texto = str(texto or '')
    if faixa_valor:
        inicio, fim = faixa_valor
        texto = texto[:inicio] + (' ' * (fim - inicio)) + texto[fim:]
    email = EMAIL_RE.search(texto)
    if email:
        return 'email', email.group(0).strip(), (email.start(), email.end())
    uuid = UUID_RE.search(texto) or TOKEN_PIX_RE.search(texto)
    if uuid:
        return 'aleatoria', uuid.group(0).strip(), (uuid.start(), uuid.end())

    pista = CHAVE_TIPO_RE.search(texto)
    tipo_explicito = None
    if pista:
        termo = pista.group(1).lower().replace('ó', 'o')
        if 'cnpj' in termo:
            tipo_explicito = 'cnpj'
        elif 'telefone' in termo or 'celular' in termo:
            tipo_explicito = 'telefone'
        elif 'cpf' in termo:
            tipo_explicito = 'cpf'
    for candidato in NUMERO_RE.finditer(texto):
        digitos = re.sub(r'\D', '', candidato.group(0))
        if len(digitos) == 14:
            tipo = 'cnpj'
        elif len(digitos) == 11:
            tipo = tipo_explicito or 'cpf'
        elif len(digitos) in (10, 12, 13):
            tipo = tipo_explicito or 'telefone'
        else:
            continue
        return tipo, candidato.group(0).strip(), (candidato.start(), candidato.end())
    return None


def sanitizar_mensagem_operacao(texto):
    """Evita persistir no histórico conversacional a chave Pix enviada pelo cliente."""
    valor, faixa_valor = extrair_valor(texto)
    chave = extrair_chave(texto, faixa_valor)
    if not chave:
        return texto
    inicio, fim = chave[2]
    return (texto[:inicio] + '[chave Pix omitida]' + texto[fim:]).strip()


def _brl(valor):
    quantia = Decimal(str(valor or 0)).quantize(Decimal('0.01'))
    texto = f'{quantia:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    return f'R$ {texto}'


def _localizar_destinatario(cursor, tipo, chave):
    chave_limpa = _normalizar_chave(tipo, chave)
    tipos = [tipo]
    if tipo == 'cpf' and len(re.sub(r'\D', '', chave_limpa)) == 11:
        tipos.append('telefone')
    elif tipo == 'telefone' and len(re.sub(r'\D', '', chave_limpa)) == 11:
        tipos.append('cpf')
    encontrados = {}
    for candidato_tipo in tipos:
        coluna = COLUNAS_POR_TIPO.get(candidato_tipo)
        if not coluna:
            continue
        valor_busca = _normalizar_chave(candidato_tipo, chave_limpa)
        cursor.execute(
            f'''SELECT K.ID_CONTA, C.TIPO_CONTA, C.NUMERO_CONTA,
                       C.NOME_FANTASIA, C.RAZAO_SOCIAL, U.NOME
                FROM CHAVE_PIX K
                INNER JOIN CONTA C ON C.ID_CONTA = K.ID_CONTA
                LEFT JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
                WHERE K.{coluna} = ?''',
            (valor_busca,),
        )
        for row in cursor.fetchall():
            id_destino = int(row[0])
            encontrados[(id_destino, candidato_tipo)] = row
    if not encontrados:
        return None, 'CHAVE_NAO_ENCONTRADA'
    contas = {chave_resultado[0] for chave_resultado in encontrados}
    if len(contas) != 1:
        return None, 'CHAVE_AMBIGUA'
    id_destino = next(iter(contas))
    id_destino, tipo_final = next(iter(encontrados))
    row = encontrados[(id_destino, tipo_final)]
    tipo_conta = 'PJ' if int(row[1] or 0) == 1 else 'PF'
    numero = re.sub(r'\D', '', str(row[2] or ''))
    nome = row[3] or row[4] or row[5] or 'Conta Arkhé'
    resumo = f'Conta {tipo_conta}' + (f' · final {numero[-4:]}' if numero else '')
    chave_normalizada = _normalizar_chave(tipo_final, chave_limpa)
    return {
        'id_conta': id_destino,
        'tipo_destino': TIPO_DESTINO_CHAVE,
        'tipo_chave': tipo_final,
        'chave_hash': hash_chave_pix(tipo_final, chave_normalizada),
        'nome': str(nome)[:160],
        'resumo': resumo,
    }, None


def _tentar_localizar_conta_propria(cursor, contexto, texto):
    alvo_proprio = bool(PALAVRAS_ALVO_PROPRIO.search(texto))
    final = re.search(r'(?i)\b(?:final|terminada?\s+em)\s*(\d{2,4})\b', texto)
    if not alvo_proprio and not final:
        return None, None
    cursor.execute(
        '''SELECT C.ID_CONTA, C.TIPO_CONTA, C.NUMERO_CONTA,
                  C.NOME_FANTASIA, C.RAZAO_SOCIAL, U.NOME
           FROM CONTA C LEFT JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
           WHERE C.ID_USUARIO = ? AND C.ID_CONTA <> ?
           ORDER BY C.ID_CONTA''',
        (contexto['id_usuario'], contexto['id_conta']),
    )
    contas = cursor.fetchall()
    if final:
        sufixo = final.group(1)
        contas = [row for row in contas if re.sub(r'\D', '', str(row[2] or '')).endswith(sufixo)]
    if len(contas) == 1:
        row = contas[0]
        id_conta = int(row[0])
        tipo = 'PJ' if int(row[1] or 0) == 1 else 'PF'
        numero = re.sub(r'\D', '', str(row[2] or ''))
        nome = row[3] or row[4] or row[5] or 'Minha outra conta'
        resumo = f'Conta {tipo}' + (f' · final {numero[-4:]}' if numero else '')
        return {
            'id_conta': id_conta, 'tipo_destino': TIPO_DESTINO_CONTA,
            'tipo_chave': None, 'chave_hash': None,
            'nome': str(nome)[:160], 'resumo': resumo,
        }, None
    if len(contas) > 1:
        opcoes = []
        for row in contas:
            numero = re.sub(r'\D', '', str(row[2] or ''))
            tipo = 'PJ' if int(row[1] or 0) == 1 else 'PF'
            opcoes.append(f'Conta {tipo} final {numero[-4:]}' if numero else f'Conta {tipo}')
        return None, 'Encontrei mais de uma conta sua. Diga o tipo e os últimos dígitos: ' + ', '.join(opcoes) + '.'
    return None, 'Não encontrei outra conta de sua titularidade. Informe uma chave Pix do destinatário.'


def _proposta(cursor, id_proposta, id_conversa, contexto, bloquear=False):
    sufixo = ' WITH LOCK' if bloquear else ''
    cursor.execute(
        f'''SELECT ID_PROPOSTA, ID_CONVERSA, ID_USUARIO, ID_CONTA_ORIGEM,
                   ID_CONTA_DESTINO, TIPO_DESTINO, TIPO_CHAVE, CHAVE_HASH,
                   VALOR, NOME_ORIGEM, NOME_DESTINATARIO,
                   CONTA_ORIGEM_RESUMO, CONTA_DESTINO_RESUMO, STATUS,
                   CRIADA_EM, EXPIRA_EM, PREPARADA_EM, CONFIRMADA_EM,
                   CANCELADA_EM, ID_MOVIMENTACAO, MOTIVO_STATUS
            FROM MAURO_PIX_PROPOSTA
            WHERE ID_PROPOSTA = ? AND ID_CONVERSA = ? AND ID_USUARIO = ?
              AND ID_CONTA_ORIGEM = ?{sufixo}''',
        (int(id_proposta), int(id_conversa), contexto['id_usuario'], contexto['id_conta']),
    )
    return cursor.fetchone()


def validar_escopo_proposta(row, id_conversa, id_usuario, id_conta):
    """Defesa adicional para a proposta pertencer à conversa, usuário e conta ativos."""
    return bool(row and int(row[1]) == int(id_conversa)
                and int(row[2]) == int(id_usuario)
                and int(row[3]) == int(id_conta))


def estado_confirmacao(status, expira_em, agora):
    """Estados puros usados pelo endpoint para impedir repetição ou uso expirado."""
    if status == 'EXECUTADA':
        return 'JA_EXECUTADA'
    if status != 'PREPARADA':
        return 'INDISPONIVEL'
    if expira_em is None or expira_em <= agora:
        return 'EXPIRADA'
    return 'PODE_CONFIRMAR'


def corpo_confirmacao_valido(corpo):
    """A rota aceita somente a credencial de confirmação, nunca parâmetros bancários."""
    return isinstance(corpo, dict) and set(corpo) == {'pin'}


def tabela_instalada(cursor):
    cursor.execute(
        """SELECT COUNT(*) FROM RDB$RELATIONS
           WHERE RDB$RELATION_NAME IN ('MAURO_PIX_PROPOSTA', 'MAURO_PIX_PIN_TENTATIVA')
             AND RDB$VIEW_BLR IS NULL"""
    )
    return int((cursor.fetchone() or (0,))[0] or 0) == 2


def _card(row):
    if not row:
        return None
    return {
        'id': int(row[0]),
        'valor': f'{Decimal(str(row[8])).quantize(Decimal("0.01")):.2f}' if row[8] is not None else None,
        'origem': row[11],
        'destinatario': row[10],
        'conta_destino': row[12],
        'tipo_destino': row[5],
        'status': row[13],
        'expira_em': row[15].isoformat(sep='T', timespec='seconds') + '-03:00' if hasattr(row[15], 'isoformat') else str(row[15]) if row[15] else None,
        'id_movimentacao': int(row[19]) if row[19] is not None else None,
        'motivo': row[20],
    }


def proposta_ativa(cursor, id_conversa, contexto, bloquear=False):
    sufixo = ' WITH LOCK' if bloquear else ''
    cursor.execute(
        f'''SELECT FIRST 1 ID_PROPOSTA, ID_CONVERSA, ID_USUARIO, ID_CONTA_ORIGEM,
                   ID_CONTA_DESTINO, TIPO_DESTINO, TIPO_CHAVE, CHAVE_HASH,
                   VALOR, NOME_ORIGEM, NOME_DESTINATARIO,
                   CONTA_ORIGEM_RESUMO, CONTA_DESTINO_RESUMO, STATUS,
                   CRIADA_EM, EXPIRA_EM, PREPARADA_EM, CONFIRMADA_EM,
                   CANCELADA_EM, ID_MOVIMENTACAO, MOTIVO_STATUS
            FROM MAURO_PIX_PROPOSTA
            WHERE ID_CONVERSA = ? AND ID_USUARIO = ? AND ID_CONTA_ORIGEM = ?
              AND STATUS IN ('COLETANDO', 'PREPARADA')
            ORDER BY ID_PROPOSTA DESC{sufixo}''',
        (id_conversa, contexto['id_usuario'], contexto['id_conta']),
    )
    return cursor.fetchone()


def obter_ultima_proposta(cursor, id_conversa, contexto):
    cursor.execute(
        '''SELECT FIRST 1 ID_PROPOSTA, ID_CONVERSA, ID_USUARIO, ID_CONTA_ORIGEM,
                   ID_CONTA_DESTINO, TIPO_DESTINO, TIPO_CHAVE, CHAVE_HASH,
                   VALOR, NOME_ORIGEM, NOME_DESTINATARIO,
                   CONTA_ORIGEM_RESUMO, CONTA_DESTINO_RESUMO, STATUS,
                   CRIADA_EM, EXPIRA_EM, PREPARADA_EM, CONFIRMADA_EM,
                   CANCELADA_EM, ID_MOVIMENTACAO, MOTIVO_STATUS
            FROM MAURO_PIX_PROPOSTA
            WHERE ID_CONVERSA = ? AND ID_USUARIO = ? AND ID_CONTA_ORIGEM = ?
            ORDER BY ID_PROPOSTA DESC''',
        (id_conversa, contexto['id_usuario'], contexto['id_conta']),
    )
    return _card(cursor.fetchone())


def _nova_proposta(cursor, id_conversa, contexto, anterior=None):
    agora = data_atual()
    cursor.execute(
        '''SELECT C.ID_CONTA, C.TIPO_CONTA, C.NUMERO_CONTA,
                  C.NOME_FANTASIA, C.RAZAO_SOCIAL, U.NOME
           FROM CONTA C LEFT JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
           WHERE C.ID_CONTA = ?''',
        (contexto['id_conta'],),
    )
    origem = cursor.fetchone()
    if not origem:
        raise RuntimeError('Conta de origem indisponível')
    tipo = 'PJ' if int(origem[1] or 0) == 1 else 'PF'
    numero = re.sub(r'\D', '', str(origem[2] or ''))
    nome_origem = origem[3] or origem[4] or origem[5] or 'Conta Arkhé'
    resumo_origem = f'Conta {tipo}' + (f' · final {numero[-4:]}' if numero else '')
    valor_anterior = anterior[8] if anterior else None
    destino_anterior = anterior[4] if anterior else None
    tipo_destino_anterior = anterior[5] if anterior else None
    tipo_chave_anterior = anterior[6] if anterior else None
    hash_anterior = anterior[7] if anterior else None
    nome_destino_anterior = anterior[10] if anterior else None
    resumo_destino_anterior = anterior[12] if anterior else None
    cursor.execute(
        '''INSERT INTO MAURO_PIX_PROPOSTA
           (ID_CONVERSA, ID_USUARIO, ID_CONTA_ORIGEM, ID_CONTA_DESTINO,
            TIPO_DESTINO, TIPO_CHAVE, CHAVE_HASH, VALOR, NOME_ORIGEM,
            NOME_DESTINATARIO, CONTA_ORIGEM_RESUMO, CONTA_DESTINO_RESUMO,
            STATUS, CRIADA_EM, EXPIRA_EM)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'COLETANDO', ?, ?)
           RETURNING ID_PROPOSTA''',
        (id_conversa, contexto['id_usuario'], contexto['id_conta'], destino_anterior,
         tipo_destino_anterior, tipo_chave_anterior, hash_anterior, valor_anterior,
         str(nome_origem)[:160], nome_destino_anterior, resumo_origem,
         resumo_destino_anterior, agora, agora + timedelta(minutes=EXPIRACAO_COLETA_MINUTOS)),
    )
    return int(cursor.fetchone()[0])


def _obter_por_id(cursor, id_proposta, id_conversa, contexto, bloquear=True):
    return _proposta(cursor, id_proposta, id_conversa, contexto, bloquear)


def _auditar(proposta, contexto, evento, resultado, *, motivo=None, valor=None,
             id_movimentacao=None, cursor=None):
    return registrar_evento_flask(
        evento=evento, resultado=resultado, motivo=motivo,
        id_usuario=contexto['id_usuario'], id_conta=contexto['id_conta'],
        valor=valor, id_registro=id_movimentacao or proposta,
        operacao='EXECUTE' if evento == 'MAURO_PIX_EXECUTADO' else 'UPDATE',
        origem=request.path if request else '/api/v1/assistente/pix',
        dados={'proposta_id': int(proposta), 'movimentacao_id': id_movimentacao},
        cursor=cursor, obrigatorio=True,
    )


def _pergunta_faltante(row):
    if row[8] is None:
        return 'Qual valor você quer enviar? Informe, por exemplo, **R$ 20,00**.'
    if row[4] is None:
        return 'Para quem será o Pix? Informe uma chave Pix ou diga que quer enviar para outra conta sua.'
    return None


def _atualizar_expiracao(cursor, id_proposta):
    agora = data_atual()
    cursor.execute(
        '''UPDATE MAURO_PIX_PROPOSTA SET STATUS = 'EXPIRADA',
               MOTIVO_STATUS = 'A proposta expirou antes da confirmação.'
           WHERE ID_PROPOSTA = ? AND STATUS IN ('COLETANDO', 'PREPARADA')''',
        (int(id_proposta),),
    )
    return agora


def _intencao_pix(texto):
    normal = str(texto or '').casefold()
    return bool(re.search(r'\b(pix|transfer\w*|mand\w*|envi\w*)\b', normal))


def processar_mensagem(cursor, id_conversa, contexto, texto, pedido_explicito):
    """Atualiza ou cria proposta no Firebird. Retorna None para fala não relacionada."""
    atual = proposta_ativa(cursor, id_conversa, contexto, bloquear=True)
    valor, faixa_valor = extrair_valor(texto)
    chave = extrair_chave(texto, faixa_valor)
    alvo_proprio, erro_conta = _tentar_localizar_conta_propria(cursor, contexto, texto)
    palavra_boleto = re.search(r'(?i)\b(boleto|cobran[cç]a)\b', texto)

    if palavra_boleto and (pedido_explicito or atual):
        return {
            'resposta': 'Por enquanto, consigo preparar propostas de Pix por chave ou para outra conta sua. Pagamentos de boleto pelo MAURO ainda não estão disponíveis; não iniciei nenhuma operação.',
            'proposta': _card(atual), 'auditoria': [], 'persistir_como_operacao': True,
        }

    if atual is None and not pedido_explicito:
        return None

    if atual is not None and atual[15] is not None and atual[15] <= data_atual():
        _atualizar_expiracao(cursor, atual[0])
        return {
            'resposta': 'A proposta anterior expirou e não pode ser confirmada. Se quiser, inicie um novo Pix para revisar os dados novamente.',
            'proposta': _card(tuple(list(atual[:13]) + ['EXPIRADA'] + list(atual[14:15]) + list(atual[15:16]) + list(atual[16:20]) + ['A proposta expirou antes da confirmação.'])),
            'auditoria': [{'evento': 'MAURO_PIX_PROPOSTA_EXPIRADA', 'resultado': 'EXPIRADA', 'id': int(atual[0]), 'valor': atual[8]}],
            'persistir_como_operacao': True,
        }

    if atual is not None and atual[13] == 'PREPARADA':
        parametro_alterado = bool(valor is not None or chave or alvo_proprio or erro_conta)
        if not parametro_alterado:
            return {
                'resposta': 'O Pix ainda não foi enviado. Para autorizar, use o botão **Confirmar Pix** no resumo e informe seu PIN na etapa segura. Para desistir, use **Cancelar**.',
                'proposta': _card(atual), 'auditoria': [], 'persistir_como_operacao': True,
            }
        cursor.execute(
            '''UPDATE MAURO_PIX_PROPOSTA SET STATUS = 'ALTERADA',
                   CANCELADA_EM = ?, MOTIVO_STATUS = 'Os parâmetros foram alterados e exigem nova conferência.'
               WHERE ID_PROPOSTA = ? AND STATUS = 'PREPARADA' ''',
            (data_atual(), int(atual[0])),
        )
        auditoria = [{'evento': 'MAURO_PIX_PROPOSTA_ALTERADA', 'resultado': 'INVALIDADA', 'id': int(atual[0]), 'valor': atual[8]}]
        id_proposta = _nova_proposta(cursor, id_conversa, contexto, atual)
        cursor.execute('SELECT * FROM MAURO_PIX_PROPOSTA WHERE ID_PROPOSTA = ?', (id_proposta,))
        atual = cursor.fetchone()
    else:
        auditoria = []
        if atual is None:
            id_proposta = _nova_proposta(cursor, id_conversa, contexto)
            cursor.execute('SELECT * FROM MAURO_PIX_PROPOSTA WHERE ID_PROPOSTA = ?', (id_proposta,))
            atual = cursor.fetchone()
        else:
            id_proposta = int(atual[0])

    id_proposta = int(atual[0])
    if valor is not None:
        cursor.execute('UPDATE MAURO_PIX_PROPOSTA SET VALOR = ? WHERE ID_PROPOSTA = ? AND STATUS = \'COLETANDO\'', (valor, id_proposta))
    if alvo_proprio:
        cursor.execute(
            '''UPDATE MAURO_PIX_PROPOSTA SET ID_CONTA_DESTINO = ?, TIPO_DESTINO = ?,
                      TIPO_CHAVE = NULL, CHAVE_HASH = NULL, NOME_DESTINATARIO = ?,
                      CONTA_DESTINO_RESUMO = ?
               WHERE ID_PROPOSTA = ? AND STATUS = 'COLETANDO' ''',
            (alvo_proprio['id_conta'], alvo_proprio['tipo_destino'], alvo_proprio['nome'], alvo_proprio['resumo'], id_proposta),
        )
    elif erro_conta:
        # Não reaproveita destinatário antigo quando a pessoa pediu outra conta própria.
        cursor.execute(
            '''UPDATE MAURO_PIX_PROPOSTA SET ID_CONTA_DESTINO = NULL, TIPO_DESTINO = NULL,
                      TIPO_CHAVE = NULL, CHAVE_HASH = NULL, NOME_DESTINATARIO = NULL,
                      CONTA_DESTINO_RESUMO = NULL
               WHERE ID_PROPOSTA = ? AND STATUS = 'COLETANDO' ''',
            (id_proposta,),
        )
    elif chave:
        cursor.execute(
            '''UPDATE MAURO_PIX_PROPOSTA SET ID_CONTA_DESTINO = NULL, TIPO_DESTINO = NULL,
                      TIPO_CHAVE = NULL, CHAVE_HASH = NULL, NOME_DESTINATARIO = NULL,
                      CONTA_DESTINO_RESUMO = NULL
               WHERE ID_PROPOSTA = ? AND STATUS = 'COLETANDO' ''',
            (id_proposta,),
        )
        encontrado, erro_chave = _localizar_destinatario(cursor, chave[0], chave[1])
        if encontrado:
            if int(encontrado['id_conta']) == int(contexto['id_conta']):
                erro_chave = 'DESTINO_IGUAL_ORIGEM'
                encontrado = None
            else:
                cursor.execute(
                    '''UPDATE MAURO_PIX_PROPOSTA SET ID_CONTA_DESTINO = ?, TIPO_DESTINO = ?,
                              TIPO_CHAVE = ?, CHAVE_HASH = ?, NOME_DESTINATARIO = ?,
                              CONTA_DESTINO_RESUMO = ?
                       WHERE ID_PROPOSTA = ? AND STATUS = 'COLETANDO' ''',
                    (encontrado['id_conta'], encontrado['tipo_destino'], encontrado['tipo_chave'],
                     encontrado['chave_hash'], encontrado['nome'], encontrado['resumo'], id_proposta),
                )
        if erro_chave == 'CHAVE_AMBIGUA':
            cursor.execute('SELECT * FROM MAURO_PIX_PROPOSTA WHERE ID_PROPOSTA = ?', (id_proposta,))
            return {'resposta': 'Essa chave está vinculada a mais de uma conta. Confira a chave ou escolha um destinatário salvo no fluxo de Pix do Arkhé.', 'proposta': _card(cursor.fetchone()), 'auditoria': auditoria, 'persistir_como_operacao': True}
        if erro_chave == 'DESTINO_IGUAL_ORIGEM':
            cursor.execute('SELECT * FROM MAURO_PIX_PROPOSTA WHERE ID_PROPOSTA = ?', (id_proposta,))
            return {'resposta': 'Essa chave pertence à conta de origem selecionada. Informe outra chave ou escolha uma conta sua diferente da conta ativa.', 'proposta': _card(cursor.fetchone()), 'auditoria': auditoria, 'persistir_como_operacao': True}
        if erro_chave == 'CHAVE_NAO_ENCONTRADA':
            cursor.execute('SELECT * FROM MAURO_PIX_PROPOSTA WHERE ID_PROPOSTA = ?', (id_proposta,))
            return {'resposta': 'Não encontrei uma conta Arkhé para essa chave. Confira os dados e envie a chave novamente. Nenhuma operação foi iniciada.', 'proposta': _card(cursor.fetchone()), 'auditoria': auditoria, 'persistir_como_operacao': True}

    cursor.execute('SELECT * FROM MAURO_PIX_PROPOSTA WHERE ID_PROPOSTA = ?', (id_proposta,))
    atual = cursor.fetchone()
    falta = _pergunta_faltante(atual)
    if erro_conta and atual[4] is None:
        falta = erro_conta
    if falta:
        return {'resposta': falta, 'proposta': _card(atual), 'auditoria': auditoria, 'persistir_como_operacao': True}

    if int(atual[4]) == int(contexto['id_conta']):
        return {'resposta': 'A conta de destino precisa ser diferente da conta ativa. Informe outra conta sua ou uma chave Pix de outro destinatário.', 'proposta': _card(atual), 'auditoria': auditoria, 'persistir_como_operacao': True}
    agora = data_atual()
    expira = agora + timedelta(minutes=EXPIRACAO_PROPOSTA_MINUTOS)
    cursor.execute(
        '''UPDATE MAURO_PIX_PROPOSTA SET STATUS = 'PREPARADA', PREPARADA_EM = ?,
                  EXPIRA_EM = ?, MOTIVO_STATUS = NULL
           WHERE ID_PROPOSTA = ? AND STATUS = 'COLETANDO'
           RETURNING ID_PROPOSTA''',
        (agora, expira, id_proposta),
    )
    if not cursor.fetchone():
        raise RuntimeError('A proposta foi alterada em outra solicitação')
    cursor.execute('SELECT * FROM MAURO_PIX_PROPOSTA WHERE ID_PROPOSTA = ?', (id_proposta,))
    preparada = cursor.fetchone()
    auditoria.append({'evento': 'MAURO_PIX_PROPOSTA_PREPARADA', 'resultado': 'PENDENTE', 'id': id_proposta, 'valor': preparada[8]})
    resposta = (
        f'Preparei uma proposta de Pix de **{_brl(preparada[8])}** da **{preparada[11]}** para '
        f'**{preparada[10]}** ({preparada[12]}). Ela expira em cinco minutos. '
        'Confira o resumo abaixo; o Pix só será enviado depois do botão de confirmação e da validação do seu PIN.'
    )
    return {'resposta': resposta, 'proposta': _card(preparada), 'auditoria': auditoria, 'persistir_como_operacao': True}


def cancelar_proposta(id_conversa, id_proposta, contexto_fn, conversa_fn):
    contexto, erro = contexto_fn()
    if erro:
        return erro
    cursor = None
    try:
        cursor = con.cursor()
        if not conversa_fn(cursor, id_conversa, contexto, bloquear=True):
            con.rollback()
            return jsonify({'mensagem': 'Conversa não encontrada.'}), 404
        row = _proposta(cursor, id_proposta, id_conversa, contexto, bloquear=True)
        if not validar_escopo_proposta(row, id_conversa, contexto['id_usuario'], contexto['id_conta']):
            con.rollback()
            return jsonify({'mensagem': 'Proposta não encontrada para esta conta.'}), 404
        if row[13] == 'EXECUTADA':
            con.rollback()
            return jsonify({'mensagem': 'Este Pix já foi executado e não pode ser cancelado por aqui.'}), 409
        status_final = row[13]
        if row[13] in ('COLETANDO', 'PREPARADA'):
            status_final = 'EXPIRADA' if row[15] and row[15] <= data_atual() else 'CANCELADA'
            cursor.execute(
                '''UPDATE MAURO_PIX_PROPOSTA SET STATUS = ?, CANCELADA_EM = ?,
                          MOTIVO_STATUS = ? WHERE ID_PROPOSTA = ? AND STATUS IN ('COLETANDO', 'PREPARADA')''',
                (status_final, data_atual(), 'Cancelada pelo cliente antes da autorização.' if status_final == 'CANCELADA' else 'Proposta expirada antes do cancelamento.', int(id_proposta)),
            )
        if status_final == 'CANCELADA':
            _auditar(id_proposta, contexto, 'MAURO_PIX_PROPOSTA_CANCELADA', 'CANCELADA', valor=row[8], cursor=cursor)
        elif status_final == 'EXPIRADA':
            _auditar(id_proposta, contexto, 'MAURO_PIX_PROPOSTA_EXPIRADA', 'EXPIRADA', valor=row[8], cursor=cursor)
        con.commit()
        cursor.execute('SELECT * FROM MAURO_PIX_PROPOSTA WHERE ID_PROPOSTA = ?', (int(id_proposta),))
        mensagem = 'Proposta cancelada. Nenhum Pix foi enviado.' if status_final == 'CANCELADA' else 'A proposta já não está ativa.'
        return jsonify({'mensagem': mensagem, 'proposta_pix': _card(cursor.fetchone())}), 200
    except Exception:
        con.rollback()
        current_app.logger.exception('Falha ao cancelar proposta Pix do MAURO')
        return jsonify({'mensagem': 'Não foi possível cancelar a proposta agora.'}), 503
    finally:
        if cursor:
            cursor.close()


def _usuario_pode_operar_conta(cursor, contexto):
    cursor.execute('SELECT ID_USUARIO, TIPO_CONTA FROM CONTA WHERE ID_CONTA = ?', (contexto['id_conta'],))
    conta = cursor.fetchone()
    if not conta:
        return False
    if int(conta[0]) == int(contexto['id_usuario']):
        return True
    if int(conta[1] or 0) != 1:
        return False
    cursor.execute(
        '''SELECT 1 FROM ACESSO_CONTA
           WHERE ID_CONTA = ? AND ID_USUARIO = ? AND STATUS = 1 WITH LOCK''',
        (contexto['id_conta'], contexto['id_usuario']),
    )
    return cursor.fetchone() is not None


def _chave_ainda_vinculada(cursor, row):
    if row[5] == TIPO_DESTINO_CONTA:
        cursor.execute(
            'SELECT 1 FROM CONTA WHERE ID_CONTA = ? AND ID_USUARIO = ?',
            (row[4], row[2]),
        )
        return cursor.fetchone() is not None
    coluna = COLUNAS_POR_TIPO.get(row[6])
    if not coluna or not row[7]:
        return False
    cursor.execute(f'SELECT {coluna} FROM CHAVE_PIX WHERE ID_CONTA = ?', (row[4],))
    for item in cursor.fetchall():
        if item[0] is not None and hash_chave_pix(row[6], _normalizar_chave(row[6], item[0])) == str(row[7]).strip():
            return True
    return False


def confirmar_proposta(id_conversa, id_proposta, contexto_fn, conversa_fn):
    contexto, erro = contexto_fn()
    if erro:
        return erro
    corpo = request.get_json(silent=True)
    if not corpo_confirmacao_valido(corpo):
        return jsonify({'mensagem': 'A confirmação aceita apenas o PIN. Valor e destinatário não podem ser alterados nesta etapa.'}), 400
    pin = corpo.get('pin') if isinstance(corpo, dict) else None
    if not isinstance(pin, str) or not re.fullmatch(r'\d{6}', pin):
        return jsonify({'mensagem': 'Informe seu PIN pessoal de seis dígitos na confirmação segura.'}), 400
    cursor = None
    eventos_publicar = []
    try:
        cursor = con.cursor()
        if not conversa_fn(cursor, id_conversa, contexto, bloquear=True):
            con.rollback()
            return jsonify({'mensagem': 'Conversa não encontrada.'}), 404
        row = _obter_por_id(cursor, id_proposta, id_conversa, contexto, bloquear=True)
        if not validar_escopo_proposta(row, id_conversa, contexto['id_usuario'], contexto['id_conta']):
            # Pode ser uma repetição após o commit; confira o resultado somente no mesmo escopo.
            row = _proposta(cursor, id_proposta, id_conversa, contexto, bloquear=True)
            if row and row[13] == 'EXECUTADA':
                con.rollback()
                return jsonify({'mensagem': 'Este Pix já foi executado.', 'proposta_pix': _card(row)}), 200
            con.rollback()
            return jsonify({'mensagem': 'Proposta não encontrada para esta conta.'}), 404
        decisao = estado_confirmacao(row[13], row[15], data_atual())
        if decisao == 'JA_EXECUTADA':
            con.rollback()
            return jsonify({'mensagem': 'Este Pix já foi executado.', 'proposta_pix': _card(row)}), 200
        if decisao == 'INDISPONIVEL':
            con.rollback()
            return jsonify({'mensagem': 'Esta proposta não está mais disponível para confirmação.', 'proposta_pix': _card(row)}), 409
        agora = data_atual()
        if decisao == 'EXPIRADA':
            _atualizar_expiracao(cursor, id_proposta)
            _auditar(id_proposta, contexto, 'MAURO_PIX_PROPOSTA_EXPIRADA', 'EXPIRADA', valor=row[8], cursor=cursor)
            con.commit()
            cursor.execute('SELECT * FROM MAURO_PIX_PROPOSTA WHERE ID_PROPOSTA = ?', (int(id_proposta),))
            return jsonify({'mensagem': 'Esta proposta expirou. Prepare um novo Pix para continuar.', 'proposta_pix': _card(cursor.fetchone())}), 410

        # Revalida o vínculo do usuário com a conta ativa na mesma transação.
        if not _usuario_pode_operar_conta(cursor, contexto):
            cursor.execute(
                '''UPDATE MAURO_PIX_PROPOSTA SET STATUS = 'RECUSADA',
                          MOTIVO_STATUS = 'O acesso à conta de origem foi revogado.'
                   WHERE ID_PROPOSTA = ? AND STATUS = 'PREPARADA' ''', (int(id_proposta),),
            )
            _auditar(id_proposta, contexto, 'MAURO_PIX_RECUSADO', 'RECUSADO', motivo='Acesso à conta de origem revogado.', valor=row[8], cursor=cursor)
            con.commit()
            return jsonify({'mensagem': 'Seu acesso à conta de origem não está mais ativo. O Pix foi recusado.', 'proposta_pix': {'id': int(id_proposta), 'status': 'RECUSADA'}}), 403
        if not _chave_ainda_vinculada(cursor, row):
            cursor.execute(
                '''UPDATE MAURO_PIX_PROPOSTA SET STATUS = 'RECUSADA',
                          MOTIVO_STATUS = 'A chave Pix não está mais vinculada ao destinatário conferido.'
                   WHERE ID_PROPOSTA = ? AND STATUS = 'PREPARADA' ''', (int(id_proposta),),
            )
            _auditar(id_proposta, contexto, 'MAURO_PIX_RECUSADO', 'RECUSADO', motivo='A chave Pix mudou após a conferência.', valor=row[8], cursor=cursor)
            con.commit()
            return jsonify({'mensagem': 'A chave Pix mudou ou deixou de estar vinculada ao destinatário conferido. Prepare uma nova proposta.', 'proposta_pix': {'id': int(id_proposta), 'status': 'RECUSADA'}}), 409

        cursor.execute('SELECT ID_USUARIO FROM USUARIO WHERE ID_USUARIO = ? WITH LOCK', (contexto['id_usuario'],))
        if not cursor.fetchone():
            con.rollback()
            return jsonify({'mensagem': 'Usuário não encontrado.'}), 401
        cursor.execute(
            '''SELECT COUNT(*) FROM MAURO_PIX_PIN_TENTATIVA
               WHERE ID_USUARIO = ? AND RESULTADO = 'RECUSADO' AND TENTATIVA_EM >= ?''',
            (contexto['id_usuario'], agora - timedelta(minutes=JANELA_TENTATIVAS_PIN_MINUTOS)),
        )
        tentativas = int((cursor.fetchone() or (0,))[0] or 0)
        if tentativas >= LIMITE_TENTATIVAS_PIN:
            con.rollback()
            _auditar(id_proposta, contexto, 'MAURO_PIX_CONFIRMACAO_RECUSADA', 'BLOQUEADO', motivo='Limite de tentativas de PIN atingido.', valor=row[8])
            return jsonify({'mensagem': 'Muitas tentativas de PIN. Aguarde 15 minutos antes de confirmar um Pix.'}), 429
        verificacao = verificar_pin_usuario(contexto['id_usuario'], pin)
        pin_pessoal = bool(verificacao.get('valido') and not verificacao.get('temporario') and not verificacao.get('legado'))
        cursor.execute(
            '''INSERT INTO MAURO_PIX_PIN_TENTATIVA
               (ID_USUARIO, ID_CONTA, ID_PROPOSTA, RESULTADO, TENTATIVA_EM)
               VALUES (?, ?, ?, ?, ?)''',
            (contexto['id_usuario'], contexto['id_conta'], int(id_proposta), 'VALIDO' if pin_pessoal else 'RECUSADO', agora),
        )
        if not pin_pessoal:
            motivo_pin = 'PIN inválido.' if not verificacao.get('valido') else 'É necessário um PIN pessoal permanente.'
            _auditar(id_proposta, contexto, 'MAURO_PIX_CONFIRMACAO_RECUSADA', 'RECUSADO', motivo=motivo_pin, valor=row[8], cursor=cursor)
            con.commit()
            if verificacao.get('valido'):
                return jsonify({'mensagem': 'Para autorizar Pix pelo MAURO, configure e use seu PIN pessoal permanente. A proposta continua pendente.'}), 403
            return jsonify({'mensagem': 'PIN incorreto. A proposta continua pendente; confira os dados e tente novamente.'}), 401

        try:
            operacao = executar_pix_para_conta(
                cursor, int(row[3]), int(row[4]), Decimal(str(row[8])), contexto['id_usuario'],
            )
        except ErroOperacaoFinanceira as erro_operacao:
            con.rollback()
            cursor.execute(
                '''UPDATE MAURO_PIX_PROPOSTA SET STATUS = 'RECUSADA', MOTIVO_STATUS = ?
                   WHERE ID_PROPOSTA = ? AND STATUS = 'PREPARADA' ''',
                (erro_operacao.mensagem[:500], int(id_proposta)),
            )
            _auditar(id_proposta, contexto, 'MAURO_PIX_RECUSADO', 'RECUSADO', motivo=erro_operacao.mensagem, valor=row[8], cursor=cursor)
            con.commit()
            cursor.execute('SELECT * FROM MAURO_PIX_PROPOSTA WHERE ID_PROPOSTA = ?', (int(id_proposta),))
            return jsonify({'mensagem': f'O Pix não foi realizado: {erro_operacao.mensagem}', 'proposta_pix': _card(cursor.fetchone())}), erro_operacao.status

        cursor.execute(
            '''UPDATE MAURO_PIX_PROPOSTA SET STATUS = 'EXECUTADA', CONFIRMADA_EM = ?,
                      ID_MOVIMENTACAO = ?, MOTIVO_STATUS = NULL
               WHERE ID_PROPOSTA = ? AND STATUS = 'PREPARADA'
               RETURNING ID_PROPOSTA''',
            (agora, int(operacao['id_movimentacao']), int(id_proposta)),
        )
        if not cursor.fetchone():
            raise RuntimeError('Proposta alterada durante a confirmação')
        _auditar(id_proposta, contexto, 'MAURO_PIX_CONFIRMADO', 'AUTORIZADO', valor=row[8], cursor=cursor)
        _auditar(id_proposta, contexto, 'MAURO_PIX_EXECUTADO', 'SUCESSO', valor=row[8], id_movimentacao=operacao['id_movimentacao'], cursor=cursor)
        con.commit()
        eventos_publicar = operacao.get('eventos') or []
        cursor.execute('SELECT * FROM MAURO_PIX_PROPOSTA WHERE ID_PROPOSTA = ?', (int(id_proposta),))
        card = _card(cursor.fetchone())
        tentar_publicar_eventos(eventos_publicar)
        return jsonify({'mensagem': f'Pix de {_brl(row[8])} enviado para {row[10]} com sucesso.', 'proposta_pix': card}), 200
    except Exception:
        con.rollback()
        current_app.logger.exception('Falha ao confirmar proposta Pix do MAURO')
        _auditar(id_proposta, contexto, 'MAURO_PIX_CONFIRMACAO', 'FALHA', motivo='Falha técnica; nenhuma confirmação adicional foi tentada.')
        return jsonify({'mensagem': 'Não foi possível confirmar o Pix agora. Confira o extrato antes de tentar novamente.'}), 503
    finally:
        if cursor:
            cursor.close()


def registrar_rotas(app_flask, contexto_fn, conversa_fn):
    app_flask.add_url_rule(
        '/api/v1/assistente/conversas/<int:id_conversa>/pix/propostas/<int:id_proposta>/cancelar',
        'mauro_cancelar_proposta_pix',
        lambda id_conversa, id_proposta: cancelar_proposta(id_conversa, id_proposta, contexto_fn, conversa_fn),
        methods=['POST'],
    )
    app_flask.add_url_rule(
        '/api/v1/assistente/conversas/<int:id_conversa>/pix/propostas/<int:id_proposta>/confirmar',
        'mauro_confirmar_proposta_pix',
        lambda id_conversa, id_proposta: confirmar_proposta(id_conversa, id_proposta, contexto_fn, conversa_fn),
        methods=['POST'],
    )
