"""Cadastros permitidos ao MAURO: proposta persistida, confirmação e PIN pessoal."""
import hashlib
import json
import re
import uuid
from datetime import timedelta

from flask import current_app, jsonify, request
from auditoria import registrar_log
from banco import con
from mauro_conversa import normalizar


ACOES = ('EDITAR_PERFIL', 'CADASTRAR_CHAVE', 'EXCLUIR_CHAVE',
         'CADASTRAR_FAVORITO', 'EDITAR_FAVORITO', 'EXCLUIR_FAVORITO')
COLUNAS_CHAVE = {'email': 'CHAVE_PIX_EMAIL', 'telefone': 'CHAVE_PIX_TELEFONE',
                 'cpf': 'CHAVE_PIX_CPF', 'cnpj': 'CHAVE_PIX_CNPJ',
                 'aleatoria': 'CHAVE_PIX_ALEATORIA'}


def instalada(cursor):
    cursor.execute("SELECT COUNT(*) FROM RDB$RELATIONS WHERE RDB$RELATION_NAME = 'MAURO_CADASTRO_PROPOSTA'")
    return bool(cursor.fetchone()[0])


def _dados(row):
    texto = row[6]
    if hasattr(texto, 'read'):
        texto = texto.read()
    return json.loads(texto)


def _consultar(cursor, id_conversa, contexto, id_proposta=None, bloquear=False):
    sql = '''SELECT FIRST 1 ID_PROPOSTA, ID_CONVERSA, ID_USUARIO, ID_CONTA,
                    ACAO, STATUS, DADOS, EXPIRA_EM, ID_REGISTRO, RESULTADO
             FROM MAURO_CADASTRO_PROPOSTA
             WHERE ID_CONVERSA = ? AND ID_USUARIO = ? AND ID_CONTA = ?'''
    parametros = [id_conversa, contexto['id_usuario'], contexto['id_conta']]
    if id_proposta is not None:
        sql += ' AND ID_PROPOSTA = ?'
        parametros.append(id_proposta)
    sql += ' ORDER BY ID_PROPOSTA DESC'
    if bloquear:
        sql += ' WITH LOCK'
    cursor.execute(sql, tuple(parametros))
    return cursor.fetchone()


def _auditar(row, contexto, resultado):
    registrar_log(usuario=contexto['id_usuario'], tabela='IA',
                  acao=f'MAURO_CADASTRO_{row[4]} / {resultado}', id_registro=int(row[0]),
                  valor_novo=f'CONVERSA_ID={row[1]} - ID_CONTA={contexto["id_conta"]} - PROPOSTA_ID={row[0]}')


def _card(row):
    if not row:
        return None
    dados = _dados(row)
    resumo = dados.get('resumo') or 'Aguardando os dados da operação.'
    return {'id': int(row[0]), 'acao': row[4], 'status': row[5], 'resumo': resumo,
            'expira_em': row[7].isoformat(), 'id_registro': row[8], 'resultado': row[9],
            'tipo_chave': dados.get('tipo') if row[4] == 'CADASTRAR_CHAVE' else None}


def ultima_proposta(cursor, id_conversa, contexto):
    if not instalada(cursor):
        return None
    return _card(_consultar(cursor, id_conversa, contexto))


def _tipo_chave(texto):
    texto = normalizar(texto)
    for tipo, padrao in (('email', r'\b(e-?mail)\b'), ('telefone', r'\b(telefone|celular|sms)\b'),
                         ('cnpj', r'\bcnpj\b'), ('cpf', r'\bcpf\b'), ('aleatoria', r'\baleatori\w*\b')):
        if re.search(padrao, texto):
            return tipo
    return None


def _valor_informado(texto, tipo):
    if tipo == 'email':
        encontrado = re.search(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}', texto)
        return encontrado.group(0).lower() if encontrado else None
    if tipo in ('cpf', 'cnpj', 'telefone'):
        encontrado = re.search(r'\b\d[\d .()+/-]{7,}\d\b', texto)
        if encontrado:
            return ''.join(c for c in encontrado.group(0) if c.isdigit())
    if tipo == 'aleatoria':
        encontrado = re.search(r'\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b', texto)
        return encontrado.group(0) if encontrado else None
    return None


def _perfil(cursor, contexto):
    cursor.execute('SELECT NOME, EMAIL, TELEFONE, CPF FROM USUARIO WHERE ID_USUARIO = ?',
                   (contexto['id_usuario'],))
    usuario = cursor.fetchone()
    if not usuario:
        raise ValueError('Seu cadastro não foi encontrado.')
    return usuario


def _titular(cursor, contexto):
    cursor.execute('SELECT ID_USUARIO, CNPJ FROM CONTA WHERE ID_CONTA = ?', (contexto['id_conta'],))
    conta = cursor.fetchone()
    if not conta or int(conta[0]) != contexto['id_usuario']:
        raise PermissionError('Somente o titular pode gerenciar as chaves Pix desta conta.')
    return conta


def _preparar_dados(cursor, contexto, acao, texto, dados):
    """Obtém valores e registros da conta; nomes do texto nunca concedem acesso."""
    resposta = str(texto).strip().strip('"')
    if acao == 'EDITAR_PERFIL':
        nome = re.search(r'\b(?:para|por|nome\s*:)\s+(.+)$', resposta, re.IGNORECASE)
        if nome:
            dados['nome'] = nome.group(1).strip().strip('"').rstrip('.')
        elif dados.get('faltante') == 'nome' and not re.search(r'[?]|\b(?:sim|nao|não|cancelar)\b', normalizar(resposta)):
            dados['nome'] = resposta
        if not dados.get('nome'):
            dados['faltante'] = 'nome'
            return 'Qual nome você quer usar no seu perfil?'
        if not 2 <= len(dados['nome']) <= 100:
            raise ValueError('Informe um nome de 2 a 100 caracteres.')
        dados['anterior'] = _perfil(cursor, contexto)[0]
        dados['resumo'] = f'Alterar seu nome de {dados["anterior"]} para {dados["nome"]}.'

    elif acao in ('CADASTRAR_CHAVE', 'EXCLUIR_CHAVE'):
        conta = _titular(cursor, contexto)
        tipo = _tipo_chave(texto)
        if tipo:
            dados['tipo'] = tipo
        if not dados.get('tipo'):
            dados['faltante'] = 'tipo'
            return 'Qual tipo de chave Pix: e-mail, telefone, CPF, CNPJ ou aleatória?'
        tipo = dados['tipo']
        coluna = COLUNAS_CHAVE[tipo]
        cursor.execute(f'SELECT ID_CHAVE_PIX, {coluna} FROM CHAVE_PIX WHERE ID_CONTA = ?', (contexto['id_conta'],))
        chave = cursor.fetchone()
        dados['anterior'] = chave[1] if chave else None
        if acao == 'EXCLUIR_CHAVE':
            if not chave or not chave[1]:
                raise ValueError('Essa chave Pix não está cadastrada na sua conta.')
            dados['id_registro'] = int(chave[0])
            dados['valor'] = chave[1]
            informado = _valor_informado(texto, tipo)
            if informado and informado != chave[1]:
                raise ValueError('A chave informada não corresponde à sua chave cadastrada. Nenhuma chave foi excluída.')
            dados['resumo'] = f'Excluir a chave Pix de tipo {tipo}, final …{str(chave[1])[-4:]}, da sua conta ativa.'
        else:
            if chave and chave[1]:
                raise ValueError('Esse tipo de chave já está cadastrado. Consulte ou exclua a chave atual antes de cadastrar outra.')
            usuario = _perfil(cursor, contexto)
            valores = {'email': usuario[1], 'telefone': usuario[2], 'cpf': usuario[3], 'cnpj': conta[1]}
            valor = str(uuid.uuid4()) if tipo == 'aleatoria' else str(valores.get(tipo) or '').strip()
            if tipo in ('telefone', 'cpf', 'cnpj'):
                valor = ''.join(c for c in valor if c.isdigit())
            if tipo == 'email':
                valor = valor.lower()
            if not valor:
                raise ValueError('Esse dado não consta no seu cadastro. Atualize seu perfil antes de criar a chave.')
            informado = _valor_informado(texto, tipo)
            if informado and informado != valor:
                raise ValueError('Só posso cadastrar uma chave vinculada ao dado confirmado do seu próprio cadastro.')
            dados['valor'] = valor
            dados['resumo'] = f'Cadastrar chave Pix do tipo {tipo} na sua conta ativa.'
            if tipo in ('email', 'telefone'):
                dados['resumo'] += ' A chave só ficará ativa após a verificação de posse já usada pelo banco.'

    elif acao in ('EDITAR_FAVORITO', 'EXCLUIR_FAVORITO'):
        identificador = re.search(r'\b(?:favorito\s*(?:n[ºo.]?\s*)?|id\s*[:=]?\s*)(\d+)\b', normalizar(texto))
        if identificador:
            dados['id_registro'] = int(identificador.group(1))
        elif dados.get('faltante') == 'id' and resposta.isdigit():
            dados['id_registro'] = int(resposta)
        if not dados.get('id_registro'):
            dados['faltante'] = 'id'
            return 'Qual o ID do favorito? Posso listar seus favoritos para você escolher.'
        cursor.execute('''SELECT ROTULO, ID_CONTA_DESTINO FROM FAVORITO_PIX
                          WHERE ID_FAVORITO = ? AND ID_CONTA = ? AND ID_USUARIO = ? AND ATIVO = 1''',
                       (dados['id_registro'], contexto['id_conta'], contexto['id_usuario']))
        favorito = cursor.fetchone()
        if not favorito:
            raise ValueError('Favorito não encontrado na sua conta e usuário.')
        dados['anterior'] = favorito[0]
        if acao == 'EDITAR_FAVORITO':
            nome = re.search(r'\b(?:para|nome\s*:)\s+(.+)$', resposta, re.IGNORECASE)
            if nome:
                dados['rotulo'] = nome.group(1).strip().strip('"').rstrip('.')
            elif dados.get('faltante') == 'rotulo':
                dados['rotulo'] = resposta
            if not dados.get('rotulo'):
                dados['faltante'] = 'rotulo'
                return 'Qual será o novo nome desse favorito?'
            if not 1 <= len(dados['rotulo']) <= 100:
                raise ValueError('O nome do favorito deve ter até 100 caracteres.')
            dados['resumo'] = f'Renomear o favorito {dados["id_registro"]}: {favorito[0]} → {dados["rotulo"]}.'
        else:
            dados['resumo'] = f'Remover dos seus favoritos: {favorito[0]} (ID {dados["id_registro"]}).'

    elif acao == 'CADASTRAR_FAVORITO':
        email = re.search(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}', texto)
        tipo = _tipo_chave(texto)
        if email:
            dados.update(tipo='email', chave=email.group(0).lower())
        elif tipo:
            valor = _valor_informado(texto, tipo)
            if valor:
                dados.update(tipo=tipo, chave=valor)
        if not dados.get('chave'):
            dados['faltante'] = 'chave'
            return 'Informe a chave Pix do destinatário e o tipo, por exemplo: e-mail pessoa@exemplo.com.'
        coluna = COLUNAS_CHAVE[dados['tipo']]
        cursor.execute(f'''SELECT C.ID_CONTA, U.NOME, C.TIPO_CONTA, C.NOME_FANTASIA, C.RAZAO_SOCIAL FROM CHAVE_PIX K
                           JOIN CONTA C ON C.ID_CONTA = K.ID_CONTA
                           JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO WHERE K.{coluna} = ?''',
                       (dados['chave'],))
        destinos = cursor.fetchall()
        if len(destinos) != 1 or int(destinos[0][0]) == contexto['id_conta']:
            raise ValueError('Informe uma chave válida de outro destinatário Arkhé.')
        dados['id_conta_destino'] = int(destinos[0][0])
        dados['nome_destinatario'] = (destinos[0][3] or destinos[0][4] or destinos[0][1]) if int(destinos[0][2]) == 1 else destinos[0][1]
        rotulo = re.search(r'\b(?:como|apelido|nome\s*:)\s+(.+)$', resposta, re.IGNORECASE)
        if rotulo:
            dados['rotulo'] = rotulo.group(1).strip().strip('"').rstrip('.')
        elif dados.get('faltante') == 'rotulo':
            dados['rotulo'] = resposta
        if not dados.get('rotulo'):
            dados['faltante'] = 'rotulo'
            return 'Com qual nome você quer salvar esse favorito?'
        if not 1 <= len(dados['rotulo']) <= 100:
            raise ValueError('O nome do favorito deve ter até 100 caracteres.')
        dados['resumo'] = f'Salvar {dados["nome_destinatario"]} nos favoritos como {dados["rotulo"]}.'
    dados.pop('faltante', None)
    return None


def processar_mensagem(cursor, id_conversa, contexto, texto, intencao):
    from funcao import data_atual
    if not instalada(cursor):
        if intencao in ACOES:
            return {'resposta': 'A atualização de cadastros do MAURO precisa ser aplicada no banco antes desta operação.', 'proposta': None}
        return None
    atual = _consultar(cursor, id_conversa, contexto)
    if intencao not in ACOES:
        if intencao != 'GERAL' or not atual or atual[5] != 'COLETANDO':
            return None
        if '?' in texto or normalizar(texto) in ('sim', 'nao', 'cancelar', 'confirme', 'confirmar'):
            return {'resposta': 'Para confirmar ou cancelar, use os botões da proposta. Não envie PIN pelo chat.', 'proposta': _card(atual)}
        if atual[7] <= data_atual():
            cursor.execute("UPDATE MAURO_CADASTRO_PROPOSTA SET STATUS = 'EXPIRADA' WHERE ID_PROPOSTA = ?", (atual[0],))
            return {'resposta': 'A coleta expirou. Faça o pedido novamente para preparar outra proposta.', 'proposta': None}
        acao, dados = atual[4], _dados(atual)
    else:
        acao, dados = intencao, {}
        if atual and atual[5] in ('COLETANDO', 'PREPARADA'):
            cursor.execute("UPDATE MAURO_CADASTRO_PROPOSTA SET STATUS = 'ALTERADA' WHERE ID_PROPOSTA = ?", (atual[0],))
        cursor.execute('''INSERT INTO MAURO_CADASTRO_PROPOSTA
                          (ID_CONVERSA, ID_USUARIO, ID_CONTA, ACAO, DADOS, EXPIRA_EM)
                          VALUES (?, ?, ?, ?, '{}', ?) RETURNING ID_PROPOSTA''',
                       (id_conversa, contexto['id_usuario'], contexto['id_conta'], acao,
                        data_atual() + timedelta(minutes=15)))
        id_proposta = int(cursor.fetchone()[0])
        atual = _consultar(cursor, id_conversa, contexto, id_proposta)
    pergunta = _preparar_dados(cursor, contexto, acao, texto, dados)
    status = 'COLETANDO' if pergunta else 'PREPARADA'
    cursor.execute('''UPDATE MAURO_CADASTRO_PROPOSTA SET DADOS = ?, STATUS = ?
                      WHERE ID_PROPOSTA = ?''', (json.dumps(dados, ensure_ascii=False), status, atual[0]))
    row = _consultar(cursor, id_conversa, contexto, atual[0])
    resposta = pergunta or (dados['resumo'] + ' Confira a proposta e confirme com seu PIN no campo seguro. Nada foi alterado ainda.')
    return {'resposta': resposta, 'proposta': _card(row)}


def _executar(cursor, contexto, row, dados):
    acao = row[4]
    if acao == 'EDITAR_PERFIL':
        cursor.execute('SELECT NOME FROM USUARIO WHERE ID_USUARIO = ? WITH LOCK', (contexto['id_usuario'],))
        if cursor.fetchone()[0] != dados['anterior']:
            raise ValueError('Seu nome mudou depois da proposta. Prepare uma nova edição.')
        cursor.execute('UPDATE USUARIO SET NOME = ? WHERE ID_USUARIO = ?',
                       (dados['nome'], contexto['id_usuario']))
        return contexto['id_usuario'], 'Seu nome foi atualizado.'

    if acao in ('CADASTRAR_CHAVE', 'EXCLUIR_CHAVE'):
        conta = _titular(cursor, contexto)
        coluna = COLUNAS_CHAVE[dados['tipo']]
        cursor.execute(f'SELECT ID_CHAVE_PIX, {coluna} FROM CHAVE_PIX WHERE ID_CONTA = ? WITH LOCK',
                       (contexto['id_conta'],))
        chave = cursor.fetchone()
        if (chave[1] if chave else None) != dados.get('anterior'):
            raise ValueError('A chave mudou depois da proposta. Prepare uma nova operação.')
        if acao == 'EXCLUIR_CHAVE':
            cursor.execute(f'UPDATE CHAVE_PIX SET {coluna} = NULL WHERE ID_CONTA = ?', (contexto['id_conta'],))
            return int(chave[0]), 'A chave Pix foi excluída.'
        usuario = _perfil(cursor, contexto)
        valor_atual = {'email': usuario[1], 'telefone': usuario[2], 'cpf': usuario[3], 'cnpj': conta[1]}.get(dados['tipo'])
        if dados['tipo'] != 'aleatoria':
            valor_atual = str(valor_atual or '').strip()
            if dados['tipo'] in ('telefone', 'cpf', 'cnpj'):
                valor_atual = ''.join(c for c in valor_atual if c.isdigit())
            if dados['tipo'] == 'email':
                valor_atual = valor_atual.lower()
            if valor_atual != dados['valor']:
                raise ValueError('Seu cadastro mudou depois da proposta. Prepare uma nova operação.')
        cursor.execute(f'SELECT 1 FROM CHAVE_PIX WHERE {coluna} = ?', (dados['valor'],))
        if cursor.fetchone():
            raise ValueError('Essa chave já está cadastrada. Nenhuma chave foi substituída.')
        if dados['tipo'] in ('email', 'telefone'):
            return None, 'Confirme a posse do e-mail ou telefone para concluir o cadastro da chave.'
        if not chave:
            cursor.execute('INSERT INTO CHAVE_PIX (ID_CONTA) VALUES (?) RETURNING ID_CHAVE_PIX', (contexto['id_conta'],))
            identificador = int(cursor.fetchone()[0])
        else:
            identificador = int(chave[0])
        cursor.execute(f'UPDATE CHAVE_PIX SET {coluna} = ? WHERE ID_CONTA = ?', (dados['valor'], contexto['id_conta']))
        return identificador, 'Sua chave Pix foi cadastrada.'

    if acao in ('EDITAR_FAVORITO', 'EXCLUIR_FAVORITO'):
        cursor.execute('''SELECT ROTULO FROM FAVORITO_PIX WHERE ID_FAVORITO = ?
                          AND ID_CONTA = ? AND ID_USUARIO = ? AND ATIVO = 1 WITH LOCK''',
                       (dados['id_registro'], contexto['id_conta'], contexto['id_usuario']))
        favorito = cursor.fetchone()
        if not favorito or favorito[0] != dados['anterior']:
            raise ValueError('O favorito mudou ou não está mais disponível. Prepare outra proposta.')
        if acao == 'EDITAR_FAVORITO':
            cursor.execute('''UPDATE FAVORITO_PIX SET ROTULO = ?, ATUALIZADO_EM = CURRENT_TIMESTAMP
                              WHERE ID_FAVORITO = ? AND ID_CONTA = ? AND ID_USUARIO = ?''',
                           (dados['rotulo'], dados['id_registro'], contexto['id_conta'], contexto['id_usuario']))
            return dados['id_registro'], 'O nome do favorito foi atualizado.'
        cursor.execute('''UPDATE FAVORITO_PIX SET ATIVO = 0, ATUALIZADO_EM = CURRENT_TIMESTAMP
                          WHERE ID_FAVORITO = ? AND ID_CONTA = ? AND ID_USUARIO = ?''',
                       (dados['id_registro'], contexto['id_conta'], contexto['id_usuario']))
        return dados['id_registro'], 'O favorito foi removido.'

    if acao == 'CADASTRAR_FAVORITO':
        coluna = COLUNAS_CHAVE[dados['tipo']]
        cursor.execute(f'SELECT ID_CONTA FROM CHAVE_PIX WHERE {coluna} = ?', (dados['chave'],))
        destinos = cursor.fetchall()
        if len(destinos) != 1 or int(destinos[0][0]) != dados['id_conta_destino']:
            raise ValueError('A chave do destinatário mudou. Prepare um novo favorito.')
        chave_hash = hashlib.sha256(f'{dados["tipo"]}\0{dados["chave"]}'.encode('utf-8')).hexdigest()
        cursor.execute('''SELECT ID_FAVORITO, ATIVO FROM FAVORITO_PIX
                          WHERE ID_CONTA = ? AND ID_USUARIO = ? AND TIPO_CHAVE = ? AND CHAVE_HASH = ?''',
                       (contexto['id_conta'], contexto['id_usuario'], dados['tipo'], chave_hash))
        existente = cursor.fetchone()
        if existente and existente[1] == 1:
            raise ValueError('Essa chave já está nos seus favoritos. Peça para editar o favorito existente.')
        if existente:
            cursor.execute('''UPDATE FAVORITO_PIX SET ATIVO = 1, ROTULO = ?, NOME_DESTINATARIO = ?,
                              ID_CONTA_DESTINO = ?, ATUALIZADO_EM = CURRENT_TIMESTAMP
                              WHERE ID_FAVORITO = ? AND ID_CONTA = ? AND ID_USUARIO = ?''',
                           (dados['rotulo'], dados['nome_destinatario'], dados['id_conta_destino'],
                            existente[0], contexto['id_conta'], contexto['id_usuario']))
            return int(existente[0]), 'O favorito foi reativado com os dados conferidos.'
        cursor.execute('''INSERT INTO FAVORITO_PIX (ID_CONTA, ID_USUARIO, ID_CONTA_DESTINO,
                          TIPO_CHAVE, CHAVE_PIX, CHAVE_HASH, ROTULO, NOME_DESTINATARIO, ATIVO)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1) RETURNING ID_FAVORITO''',
                       (contexto['id_conta'], contexto['id_usuario'], dados['id_conta_destino'],
                        dados['tipo'], dados['chave'], chave_hash, dados['rotulo'], dados['nome_destinatario']))
        return int(cursor.fetchone()[0]), 'O destinatário foi cadastrado nos seus favoritos.'
    raise ValueError('Esta operação não está disponível para o MAURO.')


def confirmar(id_conversa, id_proposta, contexto_fn, conversa_fn):
    from funcao import data_atual, verificar_pin_usuario
    from mauro_pix import _usuario_pode_operar_conta
    contexto, erro = contexto_fn()
    if erro:
        return erro
    corpo = request.get_json(silent=True)
    if not isinstance(corpo, dict) or set(corpo) != {'pin'} or not isinstance(corpo['pin'], str) or not re.fullmatch(r'\d{6}', corpo['pin']):
        return jsonify({'mensagem': 'A confirmação aceita somente seu PIN pessoal de seis dígitos.'}), 400
    cursor = None
    row = None
    try:
        cursor = con.cursor()
        if not conversa_fn(cursor, id_conversa, contexto, bloquear=True):
            con.rollback()
            return jsonify({'mensagem': 'Conversa não encontrada.'}), 404
        row = _consultar(cursor, id_conversa, contexto, id_proposta, bloquear=True)
        if not row:
            con.rollback()
            return jsonify({'mensagem': 'Proposta não encontrada nesta conta.'}), 404
        if row[5] in ('EXECUTADA', 'VERIFICANDO'):
            con.rollback()
            return jsonify({'mensagem': row[9], 'proposta_cadastro': _card(row)}), 200
        if row[5] != 'PREPARADA':
            con.rollback()
            return jsonify({'mensagem': 'Esta proposta não está pronta para confirmação.', 'proposta_cadastro': _card(row)}), 409
        if row[7] <= data_atual():
            cursor.execute("UPDATE MAURO_CADASTRO_PROPOSTA SET STATUS = 'EXPIRADA' WHERE ID_PROPOSTA = ?", (id_proposta,))
            con.commit()
            _auditar(row, contexto, 'EXPIRADA')
            return jsonify({'mensagem': 'A proposta expirou. Faça um novo pedido.'}), 410
        if not _usuario_pode_operar_conta(cursor, contexto):
            con.rollback()
            _auditar(row, contexto, 'RECUSADO')
            return jsonify({'mensagem': 'Seu acesso à conta não está mais ativo.'}), 403
        cursor.execute('SELECT ID_USUARIO FROM USUARIO WHERE ID_USUARIO = ? WITH LOCK', (contexto['id_usuario'],))
        if not cursor.fetchone():
            con.rollback()
            return jsonify({'mensagem': 'Usuário não encontrado.'}), 401
        janela = data_atual() - timedelta(minutes=15)
        cursor.execute('''SELECT COUNT(*) FROM MAURO_CADASTRO_PIN_TENTATIVA
                          WHERE ID_USUARIO = ? AND VALIDO = 0 AND CRIADA_EM >= ?''',
                       (contexto['id_usuario'], janela))
        tentativas = int(cursor.fetchone()[0])
        cursor.execute('''SELECT COUNT(*) FROM MAURO_PIX_PIN_TENTATIVA
                          WHERE ID_USUARIO = ? AND RESULTADO = 'RECUSADO' AND TENTATIVA_EM >= ?''',
                       (contexto['id_usuario'], janela))
        tentativas += int(cursor.fetchone()[0])
        if tentativas >= 5:
            con.rollback()
            _auditar(row, contexto, 'BLOQUEADO')
            return jsonify({'mensagem': 'Muitas tentativas de PIN. Aguarde 15 minutos.'}), 429
        verificacao = verificar_pin_usuario(contexto['id_usuario'], corpo['pin'])
        valido = bool(verificacao.get('valido') and not verificacao.get('temporario') and not verificacao.get('legado'))
        cursor.execute('''INSERT INTO MAURO_CADASTRO_PIN_TENTATIVA (ID_PROPOSTA, ID_USUARIO, VALIDO, CRIADA_EM)
                          VALUES (?, ?, ?, ?)''', (id_proposta, contexto['id_usuario'], int(valido), data_atual()))
        if not valido:
            con.commit()
            _auditar(row, contexto, 'PIN_RECUSADO')
            return jsonify({'mensagem': 'Use seu PIN pessoal permanente. A operação continua pendente.'}), 403
        dados = _dados(row)
        identificador, mensagem = _executar(cursor, contexto, row, dados)
        status = 'VERIFICANDO' if row[4] == 'CADASTRAR_CHAVE' and dados['tipo'] in ('email', 'telefone') else 'EXECUTADA'
        cursor.execute('''UPDATE MAURO_CADASTRO_PROPOSTA SET STATUS = ?, ID_REGISTRO = ?,
                          CONFIRMADA_EM = CURRENT_TIMESTAMP, RESULTADO = ?, EXPIRA_EM = ? WHERE ID_PROPOSTA = ?''',
                       (status, identificador, mensagem, data_atual() + timedelta(minutes=15), id_proposta))
        cursor.execute("INSERT INTO MAURO_MENSAGEM (ID_CONVERSA, PAPEL, CONTEUDO) VALUES (?, 'ASSISTENTE', ?)",
                       (id_conversa, mensagem))
        con.commit()
        _auditar(row, contexto, status)
        if row[4].endswith('FAVORITO'):
            registrar_log(usuario=contexto['id_usuario'], tabela='FAVORITO_PIX',
                          acao=row[4], id_registro=identificador,
                          valor_novo=f'ID_CONTA={contexto["id_conta"]} - PROPOSTA_ID={id_proposta}')
        resultado = {'mensagem': mensagem, 'proposta_cadastro': _card(_consultar(cursor, id_conversa, contexto, id_proposta))}
        if row[4] == 'EDITAR_PERFIL':
            resultado['perfil'] = {'nome': dados['nome']}
        return jsonify(resultado), 200
    except PermissionError as erro_permissao:
        con.rollback()
        if row:
            _auditar(row, contexto, 'RECUSADO')
        return jsonify({'mensagem': str(erro_permissao)}), 403
    except ValueError as erro_dados:
        con.rollback()
        if row:
            _auditar(row, contexto, 'RECUSADO')
        return jsonify({'mensagem': str(erro_dados)}), 409
    except Exception:
        con.rollback()
        current_app.logger.exception('Falha no cadastro confirmado pelo MAURO')
        return jsonify({'mensagem': 'Não foi possível concluir. Confira o resultado antes de tentar novamente.'}), 503
    finally:
        if cursor:
            cursor.close()


def cancelar(id_conversa, id_proposta, contexto_fn, conversa_fn):
    contexto, erro = contexto_fn()
    if erro:
        return erro
    cursor = None
    try:
        cursor = con.cursor()
        if not conversa_fn(cursor, id_conversa, contexto, bloquear=True):
            con.rollback()
            return jsonify({'mensagem': 'Conversa não encontrada.'}), 404
        row = _consultar(cursor, id_conversa, contexto, id_proposta, bloquear=True)
        if not row:
            con.rollback()
            return jsonify({'mensagem': 'Proposta não encontrada.'}), 404
        if row[5] == 'EXECUTADA':
            con.rollback()
            return jsonify({'mensagem': 'Esta operação já foi concluída.', 'proposta_cadastro': _card(row)}), 409
        if row[5] in ('COLETANDO', 'PREPARADA', 'VERIFICANDO'):
            if row[5] == 'VERIFICANDO':
                dados = _dados(row)
                cursor.execute('''UPDATE VERIFICACAO_PIX SET STATUS = 3 WHERE ID_CONTA = ?
                                  AND TIPO_CHAVE = ? AND VALOR_CHAVE = ? AND STATUS = 0''',
                               (contexto['id_conta'], dados['tipo'].upper(), dados['valor']))
            cursor.execute("UPDATE MAURO_CADASTRO_PROPOSTA SET STATUS = 'CANCELADA' WHERE ID_PROPOSTA = ?", (id_proposta,))
            con.commit()
            _auditar(row, contexto, 'CANCELADA')
        else:
            con.rollback()
        return jsonify({'mensagem': 'A proposta foi encerrada sem executar nova alteração.',
                        'proposta_cadastro': _card(_consultar(cursor, id_conversa, contexto, id_proposta))}), 200
    finally:
        if cursor:
            cursor.close()


def verificar_chave(id_conversa, id_proposta, contexto_fn, conversa_fn):
    from funcao import data_atual
    contexto, erro = contexto_fn()
    if erro:
        return erro
    cursor = None
    try:
        cursor = con.cursor()
        if not conversa_fn(cursor, id_conversa, contexto, bloquear=True):
            con.rollback()
            return jsonify({'mensagem': 'Conversa não encontrada.'}), 404
        row = _consultar(cursor, id_conversa, contexto, id_proposta, bloquear=True)
        if not row or row[4] != 'CADASTRAR_CHAVE':
            con.rollback()
            return jsonify({'mensagem': 'Proposta não encontrada.'}), 404
        if row[5] == 'VERIFICANDO':
            dados = _dados(row)
            coluna = COLUNAS_CHAVE[dados['tipo']]
            cursor.execute(f'SELECT ID_CHAVE_PIX, {coluna} FROM CHAVE_PIX WHERE ID_CONTA = ?', (contexto['id_conta'],))
            chave = cursor.fetchone()
            if chave and chave[1] == dados['valor']:
                mensagem = 'Sua chave foi verificada e está cadastrada na conta.'
                cursor.execute('''UPDATE MAURO_CADASTRO_PROPOSTA SET STATUS = 'EXECUTADA',
                                  ID_REGISTRO = ?, RESULTADO = ? WHERE ID_PROPOSTA = ?''',
                               (chave[0], mensagem, id_proposta))
                cursor.execute("INSERT INTO MAURO_MENSAGEM (ID_CONVERSA, PAPEL, CONTEUDO) VALUES (?, 'ASSISTENTE', ?)", (id_conversa, mensagem))
                con.commit()
                _auditar(row, contexto, 'EXECUTADA')
            elif row[7] <= data_atual():
                cursor.execute('''UPDATE VERIFICACAO_PIX SET STATUS = 3 WHERE ID_CONTA = ?
                                  AND TIPO_CHAVE = ? AND VALOR_CHAVE = ? AND STATUS = 0''',
                               (contexto['id_conta'], dados['tipo'].upper(), dados['valor']))
                cursor.execute("UPDATE MAURO_CADASTRO_PROPOSTA SET STATUS = 'EXPIRADA', RESULTADO = 'A confirmação expirou. Prepare um novo cadastro.' WHERE ID_PROPOSTA = ?", (id_proposta,))
                con.commit()
                _auditar(row, contexto, 'EXPIRADA')
        row = _consultar(cursor, id_conversa, contexto, id_proposta)
        return jsonify({'mensagem': row[9], 'proposta_cadastro': _card(row)}), 200
    finally:
        if cursor:
            cursor.close()


def registrar_rotas(app, contexto_fn, conversa_fn):
    base = '/api/v1/assistente/conversas/<int:id_conversa>/cadastros/<int:id_proposta>'
    app.add_url_rule(base + '/confirmar', 'mauro_confirmar_cadastro',
                     lambda id_conversa, id_proposta: confirmar(id_conversa, id_proposta, contexto_fn, conversa_fn), methods=['POST'])
    app.add_url_rule(base + '/cancelar', 'mauro_cancelar_cadastro',
                     lambda id_conversa, id_proposta: cancelar(id_conversa, id_proposta, contexto_fn, conversa_fn), methods=['POST'])
    app.add_url_rule(base + '/verificar-chave', 'mauro_verificar_chave',
                     lambda id_conversa, id_proposta: verificar_chave(id_conversa, id_proposta, contexto_fn, conversa_fn), methods=['POST'])
