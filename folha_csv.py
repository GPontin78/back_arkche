import csv
import io
import unicodedata
from flask import jsonify, request
from main import app
from banco import con
from folha import contexto_folha_pj


def somente_numeros(valor):
    return ''.join(numero for numero in str(valor or '') if numero.isdigit())


def normalizar_cabecalho(valor):
    texto = unicodedata.normalize('NFKD', str(valor or '').strip().lower())
    texto = ''.join(caractere for caractere in texto if not unicodedata.combining(caractere))
    return ' '.join(texto.replace('_', ' ').split())


def converter_salario(valor):
    valor = str(valor or '').strip().replace('R$', '').replace(' ', '')

    if ',' in valor:
        valor = valor.replace('.', '').replace(',', '.')

    return float(valor)


@app.route('/funcionarios/csv/preview', methods=['POST'])
def preview_csv_funcionarios():
    id_conta, erro = contexto_folha_pj()

    if erro:
        return erro

    arquivo = request.files.get('arquivo')

    if not arquivo:
        return jsonify({'mensagem': 'Arquivo CSV nao informado'}), 400

    if not arquivo.filename.lower().endswith('.csv'):
        return jsonify({'mensagem': 'O arquivo deve estar no formato CSV'}), 400

    cursor = None

    try:
        conteudo = arquivo.read().decode('utf-8-sig')

        if not conteudo.strip():
            return jsonify({'mensagem': 'Arquivo CSV vazio'}), 400

        linhas = conteudo.splitlines()

        if linhas and linhas[0].strip().lower().startswith('sep='):
            separador_declarado = linhas[0].strip()[4:]
            conteudo = '\n'.join(linhas[1:])
        else:
            separador_declarado = None

        amostra = conteudo[:2048]

        if separador_declarado in (';', ','):
            separador = separador_declarado
        else:
            try:
                separador = csv.Sniffer().sniff(amostra, delimiters=';,').delimiter
            except Exception:
                separador = ','

        leitor = csv.DictReader(io.StringIO(conteudo), delimiter=separador)

        if not leitor.fieldnames:
            return jsonify({'mensagem': 'Cabecalho do CSV nao encontrado'}), 400

        campos_normalizados = {normalizar_cabecalho(campo): campo for campo in leitor.fieldnames}
        campo_cpf = campos_normalizados.get('cpf')
        campo_nome = campos_normalizados.get('nome') or campos_normalizados.get('nome completo')
        campo_salario = campos_normalizados.get('salario') or campos_normalizados.get('salario mensal') or campos_normalizados.get('salario mensal (r$)')

        if not campo_cpf or not campo_nome or not campo_salario:
            return jsonify({
                'mensagem': 'O CSV precisa possuir as colunas CPF, Nome e Salario'
            }), 400

        cursor = con.cursor()

        itens = []
        cpfs_arquivo = set()
        novos = 0
        existentes = 0
        erros = 0

        for numero_linha, linha in enumerate(leitor, start=2):
            cpf = somente_numeros(linha.get(campo_cpf))
            nome = str(linha.get(campo_nome) or '').strip()
            salario_original = linha.get(campo_salario)

            item = {
                'linha': numero_linha,
                'cpf': cpf,
                'nome': nome,
                'salario': None,
                'situacao': None,
                'erro': None
            }

            if len(cpf) != 11:
                item['situacao'] = 'erro'
                item['erro'] = 'CPF deve possuir 11 digitos'
                erros += 1
                itens.append(item)
                continue

            if cpf in cpfs_arquivo:
                item['situacao'] = 'erro'
                item['erro'] = 'CPF duplicado no arquivo'
                erros += 1
                itens.append(item)
                continue

            cpfs_arquivo.add(cpf)

            if not nome:
                item['situacao'] = 'erro'
                item['erro'] = 'Nome nao informado'
                erros += 1
                itens.append(item)
                continue

            try:
                salario = converter_salario(salario_original)

                if salario <= 0:
                    raise ValueError()

                item['salario'] = salario

            except Exception:
                item['situacao'] = 'erro'
                item['erro'] = 'Salario invalido'
                erros += 1
                itens.append(item)
                continue

            cursor.execute(
                "SELECT ID_FUNCIONARIO, NOME, SALARIO, STATUS FROM FUNCIONARIO WHERE ID_CONTA_EMPRESA = ? AND CPF = ?",
                (id_conta, cpf)
            )

            funcionario = cursor.fetchone()

            cursor.execute(
                """SELECT C.ID_CONTA
                   FROM USUARIO U
                   INNER JOIN CONTA C ON C.ID_USUARIO = U.ID_USUARIO
                   WHERE U.CPF = ? AND C.TIPO_CONTA = 0
                   ORDER BY C.ID_CONTA ROWS 1""",
                (cpf,)
            )

            conta_pf = cursor.fetchone()

            item['possui_conta_arkhe'] = conta_pf is not None

            if funcionario:
                item['situacao'] = 'existente'
                item['id_funcionario'] = funcionario[0]
                item['nome_atual'] = funcionario[1]
                item['salario_atual'] = float(funcionario[2])
                item['status_atual'] = funcionario[3]
                existentes += 1
            else:
                item['situacao'] = 'novo'
                novos += 1

            itens.append(item)

        return jsonify({
            'mensagem': 'CSV analisado com sucesso',
            'total_linhas': len(itens),
            'novos': novos,
            'existentes': existentes,
            'erros': erros,
            'itens': itens
        }), 200

    except UnicodeDecodeError:
        return jsonify({
            'mensagem': 'Nao foi possivel ler o arquivo. Salve o CSV em UTF-8.'
        }), 400

    except Exception as e:
        return jsonify({
            'mensagem': 'Erro ao analisar CSV',
            'erro': str(e)
        }), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/funcionarios/csv/importar', methods=['POST'])
def importar_csv_funcionarios():
    id_conta, erro = contexto_folha_pj()

    if erro:
        return erro

    dados = request.get_json() or {}
    itens = dados.get('itens', [])

    if not itens:
        return jsonify({'mensagem': 'Nenhum funcionario informado'}), 400

    cursor = None

    try:
        cursor = con.cursor()

        criados = 0
        atualizados = 0
        ignorados = 0
        erros = []
        cpfs_importacao = set()

        for indice, item in enumerate(itens):
            cpf = somente_numeros(item.get('cpf'))
            nome = str(item.get('nome') or '').strip()
            salario = item.get('salario')
            acao = item.get('acao')
            linha_item = item.get('linha', indice + 1)

            if acao not in ('criar', 'atualizar', 'ignorar'):
                erros.append({
                    'linha': linha_item,
                    'cpf': cpf,
                    'erro': 'Acao invalida'
                })
                continue

            if cpf in cpfs_importacao:
                erros.append({
                    'linha': linha_item,
                    'cpf': cpf,
                    'erro': 'CPF duplicado na importacao'
                })
                continue

            cpfs_importacao.add(cpf)

            if acao == 'ignorar':
                ignorados += 1
                continue

            if len(cpf) != 11 or not nome:
                erros.append({
                    'linha': linha_item,
                    'cpf': cpf,
                    'erro': 'Dados invalidos'
                })
                continue

            try:
                salario = float(salario)

                if salario <= 0:
                    raise ValueError()

            except Exception:
                erros.append({
                    'linha': linha_item,
                    'cpf': cpf,
                    'erro': 'Salario invalido'
                })
                continue

            cursor.execute(
                "SELECT ID_FUNCIONARIO FROM FUNCIONARIO WHERE ID_CONTA_EMPRESA = ? AND CPF = ?",
                (id_conta, cpf)
            )

            funcionario = cursor.fetchone()

            if funcionario:
                if acao != 'atualizar':
                    ignorados += 1
                    continue

                cursor.execute(
                    "UPDATE FUNCIONARIO SET NOME = ?, SALARIO = ? WHERE ID_FUNCIONARIO = ? AND ID_CONTA_EMPRESA = ?",
                    (nome, salario, funcionario[0], id_conta)
                )

                atualizados += 1

            else:
                if acao != 'criar':
                    ignorados += 1
                    continue

                cursor.execute(
                    "SELECT ID_USUARIO FROM USUARIO WHERE CPF = ?",
                    (cpf,)
                )

                usuario = cursor.fetchone()
                id_usuario = usuario[0] if usuario else None

                cursor.execute(
                    """INSERT INTO FUNCIONARIO
                       (ID_CONTA_EMPRESA, ID_USUARIO, CPF, NOME, SALARIO, STATUS)
                       VALUES (?, ?, ?, ?, ?, 1)""",
                    (id_conta, id_usuario, cpf, nome, salario)
                )

                criados += 1

        con.commit()

        return jsonify({
            'mensagem': 'Importacao concluida',
            'criados': criados,
            'atualizados': atualizados,
            'ignorados': ignorados,
            'erros': erros,
            'quantidade_erros': len(erros)
        }), 200

    except Exception as e:
        con.rollback()

        return jsonify({
            'mensagem': 'Erro ao importar funcionarios',
            'erro': str(e)
        }), 500

    finally:
        if cursor:
            cursor.close()