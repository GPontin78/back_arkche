# ================================================================================
# IMPORTACAO DE FUNCIONARIOS POR CSV - BANCO ARKHE
# Arquivo comentado para estudo e apresentacao.
# Os comentarios explicam o funcionamento; a logica executavel foi mantida igual.
#
# IDEIA GERAL:
# 1) O usuario prepara/edita a planilha no Excel e salva como CSV UTF-8.
# 2) /funcionarios/csv/preview LE e VALIDA, mas nao grava nada.
# 3) O front mostra novos, existentes e erros para o usuario conferir.
# 4) /funcionarios/csv/importar recebe a decisao final e valida tudo novamente.
# 5) So entao cria/atualiza FUNCIONARIO e faz COMMIT.
#
# IMPORTANTE: o sistema NAO le .xlsx diretamente. Ele le texto CSV.
# Exemplo de linha: 12345678909;Sofia Silva;2500,00
# ================================================================================

# Biblioteca padrao que entende linhas e colunas de arquivos CSV.
import csv
# io permite tratar uma string em memoria como se fosse um arquivo.
import io
# unicodedata ajuda a remover acentos dos nomes das colunas.
import unicodedata
# Decimal e usado para valores monetarios com precisao de centavos.
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
# request recebe arquivo/JSON do front; jsonify cria respostas JSON.
from flask import jsonify, request
# Importa a aplicacao Flask principal para registrar as rotas.
from main import app
# Importa a conexao com o Firebird.
from banco import con
# Reaproveita do folha.py a validacao de conta PJ e a validacao de funcionario.
from folha import contexto_folha_pj, validar_dados_funcionario
# Importa a funcao que deixa CPF somente com numeros.
from funcao import normalizar_cpf


# ================================================================
# normalizar_cabecalho(valor)
# Padroniza o nome das colunas do CSV para o sistema reconhecer variacoes.
# Exemplo: 'Nome Completo', 'nome_completo' e 'NOME COMPLETO' viram algo comparavel.
# Tambem remove acentos para evitar diferenca entre 'Salário' e 'Salario'.
# ================================================================
def normalizar_cabecalho(valor):
    # Converte para minusculas, remove espacos extras e separa acentos do texto.
    texto = unicodedata.normalize('NFKD', str(valor or '').strip().lower())
    # Remove os caracteres de acento que foram separados na linha anterior.
    texto = ''.join(caractere for caractere in texto if not unicodedata.combining(caractere))
    # Troca '_' por espaco e reduz espacos repetidos. Ex.: 'nome_completo' -> 'nome completo'.
    return ' '.join(texto.replace('_', ' ').split())


# ================================================================
# converter_salario(valor)
# Converte salario escrito como texto brasileiro para Decimal.
# Exemplo: 'R$ 2.500,00' -> Decimal('2500.00').
# Observacao: esta funcao ficou disponivel no arquivo, embora a validacao principal
# hoje seja centralizada em validar_dados_funcionario() do folha.py.
# ================================================================
def converter_salario(valor):
    # Limpa R$, espacos e transforma o salario recebido em texto tratavel.
    texto = str(valor or '').strip().replace('R$', '').replace(' ', '')

    # Se nao sobrou nada, considera que o salario nao foi informado.
    if not texto:
        # Dispara erro de validacao para impedir valor invalido.
        raise ValueError()

    # Se houver virgula, assume formato brasileiro.
    if ',' in texto:
        # Ex.: '2.500,00' vira '2500.00'.
        texto = texto.replace('.', '').replace(',', '.')

    # Converte o texto limpo para Decimal.
    salario = Decimal(texto)

    # Rejeita infinito, zero e salario negativo.
    if not salario.is_finite() or salario <= 0:
        # Dispara erro de validacao para impedir valor invalido.
        raise ValueError()

    # Retorna o salario arredondado para exatamente duas casas decimais.
    return salario.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


# ================================================================
# erro_item(item, mensagens)
# Marca uma linha da previa como erro e junta todas as mensagens encontradas.
# Exemplo: ['CPF invalido', 'Salario invalido'] vira um texto separado por '; '.
# ================================================================
def erro_item(item, mensagens):
    # Marca esta linha da previa como linha com erro.
    item['situacao'] = 'erro'
    # Junta todas as mensagens de erro em um unico texto.
    item['erro'] = '; '.join(mensagens)
    # Devolve o mesmo item ja marcado para ser adicionado na previa.
    return item


# Registra a rota POST /funcionarios/csv/preview no Flask.
# O front chama este endereco para executar a funcao logo abaixo.
@app.route('/funcionarios/csv/preview', methods=['POST'])
# ================================================================
# POST /funcionarios/csv/preview
# PRIMEIRA ETAPA DA IMPORTACAO: apenas ANALISA o CSV, nao grava funcionarios.
# Fluxo: recebe arquivo -> le texto -> descobre separador -> reconhece colunas ->
# valida cada linha -> consulta banco -> devolve previa ao front.
# Exemplo: Sofia ja cadastrada -> situacao='existente'.
# Exemplo: Joao valido e novo -> situacao='novo'.
# Exemplo: CPF vazio -> situacao='erro' e importavel=False.
# ================================================================
def preview_csv_funcionarios():
    # Confere login, permissao e garante que a conta atual e PJ.
    id_conta, erro = contexto_folha_pj()

    # Se o contexto da conta nao for valido, interrompe imediatamente.
    if erro:
        # Devolve ao front o erro produzido por contexto_folha_pj().
        return erro

    # Pega do formulario HTTP o arquivo enviado no campo chamado 'arquivo'.
    arquivo = request.files.get('arquivo')

    # Sem arquivo nao existe nada para analisar.
    if not arquivo:
        # Monta a resposta JSON que sera enviada ao front.
        return jsonify({'mensagem': 'Arquivo CSV nao informado'}), 400

    # Aceita somente arquivos terminados em .csv; .xlsx nao e lido diretamente.
    if not arquivo.filename.lower().endswith('.csv'):
        # Monta a resposta JSON que sera enviada ao front.
        return jsonify({'mensagem': 'O arquivo deve estar no formato CSV'}), 400

    # Comeca com cursor=None para o finally saber se precisa fecha-lo.
    cursor = None

    # Inicio do bloco protegido; erros inesperados sao tratados abaixo.
    try:
        # Le todos os bytes do CSV e transforma em texto UTF-8; utf-8-sig tambem remove BOM do Excel.
        conteudo = arquivo.read().decode('utf-8-sig')

        # Impede processamento de arquivo vazio.
        if not conteudo.strip():
            # Monta a resposta JSON que sera enviada ao front.
            return jsonify({'mensagem': 'Arquivo CSV vazio'}), 400

        # Divide o texto em linhas. Ex.: cabecalho vira linhas[0], primeiro funcionario linhas[1].
        linhas = conteudo.splitlines()

        # Alguns CSVs do Excel comecam com 'sep=;'. Aqui detectamos essa declaracao.
        if linhas and linhas[0].strip().lower().startswith('sep='):
            # Pega somente o caractere depois de 'sep='. Ex.: 'sep=;' -> ';'.
            separador_declarado = linhas[0].strip()[4:]
            conteudo = '\n'.join(linhas[1:])
        # Caso a condicao anterior nao aconteca, segue pelo caminho alternativo.
        else:
            # Nao havia 'sep='; o sistema tera que descobrir o separador sozinho.
            separador_declarado = None

        # Usa somente os primeiros 2048 caracteres como amostra para detectar o formato.
        amostra = conteudo[:2048]

        # Se Excel ja informou ';' ou ',', usa exatamente esse separador.
        if separador_declarado in (';', ','):
            # Guarda o separador informado no arquivo.
            separador = separador_declarado
        # Caso a condicao anterior nao aconteca, segue pelo caminho alternativo.
        else:
            # Inicio do bloco protegido; erros inesperados sao tratados abaixo.
            try:
                # Sniffer analisa a amostra e tenta descobrir se as colunas usam ';' ou ','.
                separador = csv.Sniffer().sniff(amostra, delimiters=';,').delimiter
            # Se a deteccao automatica falhar, usa um padrao seguro.
            except Exception:
                # Separador padrao usado quando nao foi possivel descobrir automaticamente.
                separador = ','

        # DictReader le cada linha como dicionario: {'CPF': '...', 'Nome': '...', 'Salario': '...'}.
        leitor = csv.DictReader(io.StringIO(conteudo), delimiter=separador)

        # Sem nomes de colunas no cabecalho, nao da para saber onde esta CPF/nome/salario.
        if not leitor.fieldnames:
            # Monta a resposta JSON que sera enviada ao front.
            return jsonify({'mensagem': 'Cabecalho do CSV nao encontrado'}), 400

        # Cria um mapa com nomes de colunas normalizados para aceitar pequenas variacoes do cabecalho.
        campos_normalizados = {normalizar_cabecalho(campo): campo for campo in leitor.fieldnames if campo is not None}
        # Descobre qual coluna original corresponde ao CPF.
        campo_cpf = campos_normalizados.get('cpf')
        # Aceita coluna chamada 'nome' ou 'nome completo'.
        campo_nome = campos_normalizados.get('nome') or campos_normalizados.get('nome completo')
        # Aceita variacoes de 'salario', inclusive 'salario mensal (r$)'.
        campo_salario = campos_normalizados.get('salario') or campos_normalizados.get('salario mensal') or campos_normalizados.get('salario mensal (r$)')

        # Lista usada para informar quais colunas obrigatorias nao foram encontradas.
        colunas_ausentes = []
        # Confere se existe coluna de CPF.
        if not campo_cpf:
            # Registra CPF como coluna ausente.
            colunas_ausentes.append('CPF')
        # Confere se existe coluna de nome.
        if not campo_nome:
            # Registra nome como coluna ausente.
            colunas_ausentes.append('Nome completo')
        # Confere se existe coluna de salario.
        if not campo_salario:
            # Registra salario como coluna ausente.
            colunas_ausentes.append('Salario mensal')

        # Se faltou qualquer coluna obrigatoria, nao tenta ler os funcionarios.
        if colunas_ausentes:
            # Monta a resposta JSON que sera enviada ao front.
            return jsonify({
                'mensagem': 'O CSV precisa possuir as colunas CPF, Nome completo e Salario mensal.',
                'colunas_ausentes': colunas_ausentes
            }), 400

        # Abre cursor do Firebird para consultar funcionarios/usuarios durante a previa ou importacao.
        cursor = con.cursor()

        # Lista final de linhas analisadas que sera enviada ao front.
        itens = []
        # Set guarda CPFs ja vistos para detectar CPF repetido dentro do mesmo arquivo.
        cpfs_arquivo = set()
        # Contador de funcionarios novos.
        novos = 0
        # Contador de funcionarios que ja existem nesta empresa.
        existentes = 0
        # Contador de linhas com erro.
        erros = 0

        # Percorre cada funcionario. start=2 porque linha 1 e o cabecalho do CSV.
        for numero_linha, linha in enumerate(leitor, start=2):
            # Ignora linha totalmente vazia no meio/final da planilha.
            if not any(str(valor or '').strip() for valor in linha.values() if not isinstance(valor, list)):
                # Pula imediatamente para a proxima linha/item do loop.
                continue

            # Usa a MESMA validacao do cadastro manual: CPF real, nome presente e salario valido.
            cpf, nome, salario, problemas = validar_dados_funcionario(
                linha.get(campo_cpf),
                linha.get(campo_nome),
                linha.get(campo_salario)
            )

            # Monta o objeto que representa esta linha na tela de previa.
            item = {
                # Guarda o numero original da linha para mostrar exatamente onde existe erro.
                'linha': numero_linha,
                # CPF ja normalizado, somente numeros.
                'cpf': cpf,
                # True somente quando nenhuma validacao de CPF encontrou problema.
                'cpf_valido': not any(problema.startswith('CPF ') for problema in problemas),
                # Nome tratado pela validacao central.
                'nome': nome,
                # Converte Decimal para float apenas para conseguir serializar no JSON.
                'salario': float(salario) if salario is not None else None,
                # Sera preenchido depois como 'novo', 'existente' ou 'erro'.
                'situacao': None,
                # Comeca sem mensagem de erro.
                'erro': None,
                # Comeca assumindo que ainda nao sabemos se existe USUARIO Arkhe.
                'possui_usuario_arkhe': False,
                # Comeca assumindo que ainda nao sabemos se existe conta PF Arkhe.
                'possui_conta_arkhe': False,
                # So vira True depois que a linha passar por todas as validacoes.
                'importavel': False
            }

            # So verifica duplicidade no arquivo se o CPF em si for valido.
            if item['cpf_valido']:
                # Detecta o mesmo CPF aparecendo duas vezes no mesmo CSV.
                if cpf in cpfs_arquivo:
                    # Adiciona erro para impedir importar a segunda ocorrencia.
                    problemas.append('CPF duplicado no arquivo')
                # Caso a condicao anterior nao aconteca, segue pelo caminho alternativo.
                else:
                    # Marca esse CPF como ja visto neste arquivo.
                    cpfs_arquivo.add(cpf)

            # Qualquer problema transforma a linha em erro antes de consultar/gravar no banco.
            if problemas:
                # Adiciona a linha invalida na previa para o usuario poder enxergar o motivo.
                itens.append(erro_item(item, problemas))
                # Soma uma linha ao contador de erros.
                erros += 1
                # Pula imediatamente para a proxima linha/item do loop.
                continue

            # Procura se este CPF ja esta cadastrado como funcionario desta empresa.
            cursor.execute(
                "SELECT ID_FUNCIONARIO, NOME, SALARIO, STATUS FROM FUNCIONARIO WHERE ID_CONTA_EMPRESA = ? AND CPF = ?",
                (id_conta, cpf)
            )
            # Pega o funcionario encontrado; None significa que esse CPF ainda nao esta na empresa.
            funcionario = cursor.fetchone()

            # Procura se o CPF pertence a um USUARIO Arkhe e se ele possui conta PF.
            cursor.execute(
                """SELECT U.ID_USUARIO, C.ID_CONTA
                   FROM USUARIO U
                   LEFT JOIN CONTA C ON C.ID_USUARIO = U.ID_USUARIO AND C.TIPO_CONTA = 0
                   WHERE U.CPF = ?
                   ORDER BY C.ID_CONTA NULLS LAST ROWS 1""",
                (cpf,)
            )
            # Pega USUARIO/conta PF encontrados para esse CPF.
            conta_arkhe = cursor.fetchone()

            # Informa ao front se existe uma pessoa Arkhe com esse CPF.
            item['possui_usuario_arkhe'] = conta_arkhe is not None
            # Informa ao front se essa pessoa possui uma conta PF apta a receber salario.
            item['possui_conta_arkhe'] = bool(conta_arkhe and conta_arkhe[1] is not None)

            # Linha valida: agora pode ser enviada para a etapa de importacao.
            item['importavel'] = True

            # Se ja existe na tabela FUNCIONARIO, classifica como existente.
            if funcionario:
                # O front mostrara 'Ja cadastrado' e permite atualizar ou ignorar.
                item['situacao'] = 'existente'
                # Guarda o ID atual para referencia na previa.
                item['id_funcionario'] = funcionario[0]
                # Guarda o nome que ja esta salvo no banco para comparar com o CSV.
                item['nome_atual'] = funcionario[1]
                # Guarda o salario atual para o front mostrar 'Atual' x 'No arquivo'.
                item['salario_atual'] = float(funcionario[2]) if funcionario[2] is not None else None
                # Guarda se o funcionario existente esta ativo ou inativo.
                item['status_atual'] = funcionario[3]
                # Soma um ao contador de funcionarios existentes.
                existentes += 1
            # Caso a condicao anterior nao aconteca, segue pelo caminho alternativo.
            else:
                # CPF ainda nao cadastrado nesta empresa: classifica como novo.
                item['situacao'] = 'novo'
                # Soma um ao contador de novos funcionarios.
                novos += 1

            # Adiciona a linha analisada na lista final da previa.
            itens.append(item)

        # Se nenhuma linha util foi encontrada, devolve erro em vez de previa vazia.
        if not itens:
            # Monta a resposta JSON que sera enviada ao front.
            return jsonify({'mensagem': 'O CSV nao possui linhas de funcionarios para analisar'}), 400

        # Monta a resposta JSON que sera enviada ao front.
        return jsonify({
            'mensagem': 'CSV analisado com sucesso',
            'total_linhas': len(itens),
            'novos': novos,
            'existentes': existentes,
            'erros': erros,
            'itens': itens
        }), 200

    # Erro especifico quando o arquivo nao esta em codificacao UTF-8.
    except UnicodeDecodeError:
        # Monta a resposta JSON que sera enviada ao front.
        return jsonify({
            'mensagem': 'Nao foi possivel ler o arquivo. Salve o CSV em UTF-8.'
        }), 400

    # Captura qualquer erro inesperado e devolve mensagem controlada.
    except Exception as e:
        # Monta a resposta JSON que sera enviada ao front.
        return jsonify({
            'mensagem': 'Erro ao analisar CSV',
            'erro': str(e)
        }), 500

    # Executa no final tanto em sucesso quanto em erro.
    finally:
        # So tenta fechar se o cursor realmente foi aberto.
        if cursor:
            # Fecha o cursor do Firebird para liberar o recurso.
            cursor.close()


# Registra a rota POST /funcionarios/csv/importar no Flask.
# O front chama este endereco para executar a funcao logo abaixo.
@app.route('/funcionarios/csv/importar', methods=['POST'])
# ================================================================
# POST /funcionarios/csv/importar
# SEGUNDA ETAPA: recebe do front apenas as linhas escolhidas e grava no banco.
# Mesmo depois da previa, o backend valida TUDO novamente por seguranca.
# Cada item vem com acao: 'criar', 'atualizar' ou 'ignorar'.
# Ao final faz um unico COMMIT com o lote processado.
# ================================================================
def importar_csv_funcionarios():
    # Confere login, permissao e garante que a conta atual e PJ.
    id_conta, erro = contexto_folha_pj()

    # Se o contexto da conta nao for valido, interrompe imediatamente.
    if erro:
        # Devolve ao front o erro produzido por contexto_folha_pj().
        return erro

    # Na importacao, os dados chegam como JSON montado pelo front a partir da previa.
    dados = request.get_json() or {}
    # Extrai do JSON a lista de funcionarios escolhidos para processar.
    itens = dados.get('itens', [])

    # Se nenhuma linha util foi encontrada, devolve erro em vez de previa vazia.
    if not itens:
        # Monta a resposta JSON que sera enviada ao front.
        return jsonify({'mensagem': 'Nenhum funcionario informado'}), 400

    # Comeca com cursor=None para o finally saber se precisa fecha-lo.
    cursor = None

    # Inicio do bloco protegido; erros inesperados sao tratados abaixo.
    try:
        # Abre cursor do Firebird para consultar funcionarios/usuarios durante a previa ou importacao.
        cursor = con.cursor()

        # Contador de funcionarios inseridos.
        criados = 0
        # Contador de funcionarios existentes atualizados.
        atualizados = 0
        # Contador de linhas que o usuario escolheu nao alterar.
        ignorados = 0
        # Lista detalhada de erros ocorridos linha por linha.
        erros = []
        # Detecta CPF repetido tambem na etapa final, nao confiando apenas na previa.
        cpfs_importacao = set()

        # Processa cada item recebido do front.
        for indice, item in enumerate(itens):
            # Usa a MESMA validacao do cadastro manual: CPF real, nome presente e salario valido.
            cpf, nome, salario, problemas = validar_dados_funcionario(
                item.get('cpf'),
                item.get('nome'),
                item.get('salario')
            )
            # Le a decisao do front: criar, atualizar ou ignorar.
            acao = item.get('acao')
            # Mantem o numero da linha original para relatar erro ao usuario.
            linha_item = item.get('linha', indice + 1)

            # Bloqueia qualquer acao diferente das tres permitidas.
            if acao not in ('criar', 'atualizar', 'ignorar'):
                # Adiciona um erro detalhado ao resultado da importacao.
                erros.append({
                    'linha': linha_item,
                    # CPF ja normalizado, somente numeros.
                    'cpf': cpf,
                    'erro': 'Acao invalida'
                })
                # Pula imediatamente para a proxima linha/item do loop.
                continue

            # Impede que o mesmo CPF seja processado duas vezes no mesmo lote.
            if cpf and cpf in cpfs_importacao:
                # Adiciona um erro detalhado ao resultado da importacao.
                erros.append({
                    'linha': linha_item,
                    # CPF ja normalizado, somente numeros.
                    'cpf': cpf,
                    'erro': 'CPF duplicado na importacao'
                })
                # Pula imediatamente para a proxima linha/item do loop.
                continue

            # So adiciona ao controle de duplicidade quando existe CPF.
            if cpf:
                # Marca esse CPF como ja processado neste lote.
                cpfs_importacao.add(cpf)

            # Se o usuario escolheu ignorar, nao altera nada no banco.
            if acao == 'ignorar':
                # Soma uma linha ao contador de ignorados.
                ignorados += 1
                # Pula imediatamente para a proxima linha/item do loop.
                continue

            # Qualquer problema transforma a linha em erro antes de consultar/gravar no banco.
            if problemas:
                # Adiciona um erro detalhado ao resultado da importacao.
                erros.append({
                    'linha': linha_item,
                    # CPF ja normalizado, somente numeros.
                    'cpf': cpf,
                    'erro': '; '.join(problemas)
                })
                # Pula imediatamente para a proxima linha/item do loop.
                continue

            # Na importacao, confere novamente se esse CPF ja existe na empresa.
            cursor.execute(
                "SELECT ID_FUNCIONARIO FROM FUNCIONARIO WHERE ID_CONTA_EMPRESA = ? AND CPF = ?",
                (id_conta, cpf)
            )
            # Pega o funcionario encontrado; None significa que esse CPF ainda nao esta na empresa.
            funcionario = cursor.fetchone()

            # Se ja existe na tabela FUNCIONARIO, classifica como existente.
            if funcionario:
                # Funcionario existente so muda se a acao enviada for exatamente 'atualizar'.
                if acao != 'atualizar':
                    # Soma uma linha ao contador de ignorados.
                    ignorados += 1
                    # Pula imediatamente para a proxima linha/item do loop.
                    continue

                # Atualiza nome e salario do funcionario existente com os valores do CSV.
                cursor.execute(
                    "UPDATE FUNCIONARIO SET NOME = ?, SALARIO = ? WHERE ID_FUNCIONARIO = ? AND ID_CONTA_EMPRESA = ?",
                    (nome, salario, funcionario[0], id_conta)
                )
                # Soma um funcionario atualizado.
                atualizados += 1

            # Caso a condicao anterior nao aconteca, segue pelo caminho alternativo.
            else:
                # CPF novo so e inserido quando a acao for exatamente 'criar'.
                if acao != 'criar':
                    # Soma uma linha ao contador de ignorados.
                    ignorados += 1
                    # Pula imediatamente para a proxima linha/item do loop.
                    continue

                # Para funcionario novo, procura se o CPF ja corresponde a um USUARIO Arkhe.
                cursor.execute(
                    "SELECT ID_USUARIO FROM USUARIO WHERE CPF = ?",
                    (cpf,)
                )
                # Guarda o USUARIO Arkhe encontrado, se esse CPF ja existir no banco.
                usuario = cursor.fetchone()
                # Vincula ao USUARIO existente; se nao houver, FUNCIONARIO fica com ID_USUARIO NULL.
                id_usuario = usuario[0] if usuario else None

                # Insere um novo FUNCIONARIO ligado a empresa e, quando existir, ao ID_USUARIO.
                cursor.execute(
                    """INSERT INTO FUNCIONARIO
                       (ID_CONTA_EMPRESA, ID_USUARIO, CPF, NOME, SALARIO, STATUS)
                       VALUES (?, ?, ?, ?, ?, 1)""",
                    (id_conta, id_usuario, cpf, nome, salario)
                )
                # Soma um funcionario criado.
                criados += 1

        # COMMIT confirma de uma vez todas as insercoes/atualizacoes feitas no lote.
        con.commit()

        # Monta a resposta JSON que sera enviada ao front.
        return jsonify({
            'mensagem': 'Importacao concluida',
            'criados': criados,
            'atualizados': atualizados,
            'ignorados': ignorados,
            'erros': erros,
            'quantidade_erros': len(erros)
        }), 200

    # Captura qualquer erro inesperado e devolve mensagem controlada.
    except Exception as e:
        # Em erro inesperado, desfaz alteracoes ainda nao confirmadas.
        con.rollback()

        # Monta a resposta JSON que sera enviada ao front.
        return jsonify({
            'mensagem': 'Erro ao importar funcionarios',
            'erro': str(e)
        }), 500

    # Executa no final tanto em sucesso quanto em erro.
    finally:
        # So tenta fechar se o cursor realmente foi aberto.
        if cursor:
            # Fecha o cursor do Firebird para liberar o recurso.
            cursor.close()
