"""Interpretação e memória contextual do MAURO web.

Este módulo só interpreta linguagem e períodos. Nunca executa movimentações,
decide permissões, acessa outro usuário ou aceita ações oriundas do modelo.
"""
import re
import unicodedata
from datetime import date, datetime, timedelta


def normalizar(texto):
    texto = unicodedata.normalize('NFKD', str(texto or '').casefold())
    return re.sub(r'\s+', ' ', ''.join(c for c in texto if not unicodedata.combining(c))).strip()


def ultima_pergunta(historico):
    for mensagem in reversed(historico or ()):
        if mensagem.get('papel') == 'USUARIO':
            return str(mensagem.get('conteudo') or '')
    return ''


def assunto_anterior(historico):
    """Assunto mais recente do usuário, não das instruções de um assistente."""
    anterior = normalizar(ultima_pergunta(historico))
    if not anterior:
        return None
    if re.search(r'\b(python|javascript|sql|codigo|programac\w*|hello world|hello word)\b', anterior):
        return 'PROGRAMACAO'
    if re.search(r'\b(pix|chave pix|transfer\w*)\b', anterior):
        return 'PIX'
    if re.search(r'\b(receb\w*|entrada\w*|receita\w*)\b', anterior):
        return 'RECEITAS'
    if re.search(r'\b(gast\w*|despes\w*|paguei|pagamento\w*)\b', anterior):
        return 'DESPESAS'
    if re.search(r'\b(moviment\w*|extrat\w*|transac\w*)\b', anterior):
        return 'MOVIMENTACOES'
    if re.search(r'\b(saldo|slado|salfo)\b', anterior):
        return 'SALDO'
    if re.search(r'\b(carta\w*|fatura\w*)\b', anterior):
        return 'CARTAO'
    return None


def intencao_especial(texto, historico=()):
    """Casos conversacionais e novas consultas que o roteador legado não cobre."""
    n = normalizar(texto)
    if re.search(r'\b(?:alter\w*|edit\w*|modific\w*|aument\w*|diminu\w*|ajust\w*)\b.*\b(?:meu|minha|o)?\s*(?:saldo|slado|salfo)\b', n):
        return 'ALTERAR_SALDO'
    if re.search(r'\b(?:edit\w*|alter\w*|mud\w*|troqu\w*)\b.*\b(?:meu )?nome\b', n):
        return 'EDITAR_PERFIL'
    if re.search(r'\b(?:apag\w*|exclu\w*|remov\w*|delet\w*)\b.*\bchave\w*\s+pix\b', n):
        return 'EXCLUIR_CHAVE'
    if re.search(r'\b(?:cria\w*|gera\w*|quero\w*|faz\w*)\b.*\bcarta\w*\b.*\bvirtual\b', n):
        return 'CARTAO_VIRTUAL'
    if re.search(r'\b(?:para\s+quem|quem\s+recebeu|destinatari\w*)\b.*\b(?:mais|maior|frequente)\b', n) and re.search(r'\b(?:envi\w*|mand\w*|transfer\w*|pix|dinheiro|pag\w*)\b', n):
        return 'DESTINATARIOS_FREQUENTES'
    if re.search(r'\b(?:mais\s+envi\w*|mais\s+transfer\w*)\b', n) and re.search(r'\b(?:quem|pessoa|destinatari\w*)\b', n):
        return 'DESTINATARIOS_FREQUENTES'
    if re.search(r'\b(?:quem sou eu|qual e o meu nome|qual meu nome|qual e minha conta|qual a minha conta)\b', n):
        return 'PERFIL'
    if re.search(r'\b(?:que dia e hoje|qual (?:e )?a data de hoje|qual a data atual|que data e hoje|que horas sao|qual (?:e )?a hora)\b', n):
        return 'DATA_ATUAL'
    if re.search(r'\b(?:o que voce (?:pode|consegue) fazer|em que voce (?:pode|consegue) ajudar|como voce pode me ajudar|quais suas funcionalidades|o que o mauro faz)\b', n):
        return 'CAPACIDADES'
    if re.search(r'\b(?:sobre o que (?:a gente|nos) fal\w*|do que (?:a gente|nos) convers\w*|o que (?:a gente|nos) convers\w*|resume? nossa conversa|resum\w* a conversa)\b', n):
        return 'RESUMO_CONVERSA'
    if re.search(r'\b(?:saldo|slado|salfo|saldp|sado|slado|sald0)\b', n) and len(n.split()) <= 8:
        return 'SALDO'
    if re.search(r'\b(?:lista\w*|mostr\w*|detalh\w*|quais)\b.*\b(?:despes\w*|gastos?|saidas?)\b', n):
        return 'LISTAR_DESPESAS'
    if re.search(r'\b(?:lista\w*|mostr\w*|detalh\w*|quais)\b.*\b(?:receb\w*|entradas?|receitas?)\b', n):
        return 'LISTAR_RECEITAS'
    # Referências só podem herdar o assunto se for continuação real da conversa.
    if re.fullmatch(r'(?:e\s+)?(?:quais\s+(?:foram|sao)\s+(?:elas|eles)|me\s+mostre\s+(?:elas|eles)|lista\s+(?:elas|eles)|quero\s+ver\s+(?:elas|eles)|detalhe\s+(?:isso|essas?|esses?))(?:\s+(?:por\s+favor|pra\s+mim))?[.!?]*', n):
        anterior = assunto_anterior(historico)
        if anterior == 'DESPESAS':
            return 'LISTAR_DESPESAS'
        if anterior == 'RECEITAS':
            return 'LISTAR_RECEITAS'
        if anterior == 'MOVIMENTACOES':
            return 'MOVIMENTACOES'
    return None


def assunto_bancario_em_andamento(historico):
    return assunto_anterior(historico) in ('PIX', 'DESPESAS', 'RECEITAS', 'MOVIMENTACOES', 'SALDO', 'CARTAO')


def mensagem_complementar_pix(texto):
    n = normalizar(texto)
    # Aceita uma resposta a "qual valor?" sem confundi-la com comandos livres.
    return bool(re.fullmatch(r'(?:eu\s+)?(?:quero\s+)?(?:de\s+)?(?:r\$\s*)?\d{1,10}(?:[,.]\d{1,2})?\s*(?:reais?)?[.!?]*', n)
                or re.fullmatch(r'(?:a\s+)?(?:chave\s+(?:e|pix)\s+)?[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}', n))


def _data_pt(data_str, ano):
    dia, mes, *ano_bruto = re.findall(r'\d+', data_str)
    ano_final = int(ano_bruto[0]) if ano_bruto else ano
    if ano_final < 100:
        ano_final += 2000
    return date(ano_final, int(mes), int(dia))


def periodo_solicitado(texto, historico=(), agora=None, padrao='mes'):
    """Retorna intervalo [início, fim) para uso com parâmetros SQL.

    Só herda período de uma pergunta anterior se o texto for referência curta.
    """
    hoje = (agora or datetime.now()).date() if isinstance(agora, datetime) or agora is None else agora
    n = normalizar(texto)
    match = re.search(r'\b(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s*(?:a|ate|e)\s*(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\b', n)
    if match:
        try:
            inicio, fim_inclusivo = _data_pt(match.group(1), hoje.year), _data_pt(match.group(2), hoje.year)
            if inicio <= fim_inclusivo and (fim_inclusivo-inicio).days <= 366:
                return inicio, fim_inclusivo + timedelta(days=1), f'de {inicio:%d/%m/%Y} a {fim_inclusivo:%d/%m/%Y}'
        except (ValueError, IndexError, TypeError):
            pass
    if re.search(r'\bontem\b', n):
        return hoje-timedelta(days=1), hoje, 'ontem'
    if re.search(r'\bhoje\b', n):
        return hoje, hoje+timedelta(days=1), 'hoje'
    if re.search(r'\b(?:semana passada|ultima semana fechada)\b', n):
        inicio=hoje-timedelta(days=hoje.weekday()+7)
        return inicio,inicio+timedelta(days=7),'na semana passada'
    if re.search(r'\b(?:mes passado|ultimo mes fechado)\b', n):
        primeiro=hoje.replace(day=1)
        fim=primeiro
        ultimo=fim-timedelta(days=1)
        return ultimo.replace(day=1),fim,'no mês passado'
    if re.search(r'\b(?:ultimos?\s+(?:7|sete)\s+dias|esta semana|nessa semana|nesta semana)\b', n):
        inicio=hoje-timedelta(days=6)
        return inicio,hoje+timedelta(days=1),'nos últimos sete dias'
    if re.search(r'\b(?:este mes|nesse mes|neste mes|mes atual|do mes|desse mes)\b', n):
        return hoje.replace(day=1),hoje+timedelta(days=1),'neste mês'
    if re.search(r'\b(?:ano atual|este ano|neste ano)\b', n):
        return hoje.replace(month=1,day=1),hoje+timedelta(days=1),'neste ano'
    if re.fullmatch(r'(?:e\s+)?(?:quais\s+(?:foram|sao)\s+(?:elas|eles)|me\s+mostre\s+(?:elas|eles)|lista\s+(?:elas|eles)|detalhe\s+(?:isso|essas?|esses?))(?:\s+(?:por\s+favor|pra\s+mim))?[.!?]*',n):
        anterior=ultima_pergunta(historico)
        if anterior:
            return periodo_solicitado(anterior,(),hoje,padrao)
    if padrao == 'todos':
        return None,None,'em todo o histórico da conta'
    if padrao == 'semana':
        return hoje-timedelta(days=6),hoje+timedelta(days=1),'nos últimos sete dias'
    return hoje.replace(day=1),hoje+timedelta(days=1),'neste mês'


def resumo_conversa(historico):
    rotulos = {'SALDO':'saldo', 'DESPESAS':'despesas', 'RECEITAS':'recebimentos',
               'MOVIMENTACOES':'movimentações', 'PIX':'Pix', 'CARTAO':'cartões e faturas'}
    assuntos=[]
    for m in historico or ():
        if m.get('papel') != 'USUARIO':
            continue
        assunto=assunto_anterior([m])
        if assunto in rotulos and rotulos[assunto] not in assuntos:
            assuntos.append(rotulos[assunto])
    if not assuntos:
        return 'Pelas mensagens recentes que tenho aqui, ainda não conversamos sobre uma consulta específica do Arkhé.'
    return 'Pelas mensagens recentes, falamos sobre ' + ', '.join(assuntos[:-1]) + (' e ' if len(assuntos)>1 else '') + assuntos[-1] + '. Posso retomar qualquer um desses assuntos.'
