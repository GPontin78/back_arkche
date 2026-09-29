import csv
import io
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from flask import jsonify, request
from main import app
from banco import con
from folha import contexto_folha_pj
from funcao import normalizar_cpf, validar_cpf


def normalizar_cabecalho(valor):
    texto = unicodedata.normalize('NFKD', str(valor or '').strip().lower())
    texto = ''.join(caractere for caractere in texto if not unicodedata.combining(caractere))
    return ' '.join(texto.replace('_', ' ').split())


def converter_salario(valor):
    texto = str(valor or '').strip().replace('R$', '').replace(' ', '')

    if not texto:
        raise ValueError()

    if ',' in texto:
        texto = texto.replace('.', '').replace(',', '.')

    salario = Decimal(texto)

    if not salario.is_finite() or salario <= 0:
        raise ValueError()

    return salario.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def erro_item(item, mensagens):
    item['situacao'] = 'erro'
    item['erro'] = '; '.join(mensagens)
    return item


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

        campos_normalizados = {normalizar_cabecalho(campo): campo for campo in leitor.fieldnames if campo is not None}
        campo_cpf = campos_normalizados.get('cpf')
        campo_nome = campos_normalizados.get('nome') or campos_normalizados.get('nome completo')
        campo_salario = campos_normalizados.get('salario') or campos_normalizados.get('salario mensal') or campos_normalizados.get('salario mensal (r$)')

        colunas_ausentes = []
        if not campo_cpf:
            colunas_ausentes.append('CPF')
        if not campo_nome:
            colunas_ausentes.append('Nome completo')
        if not campo_salario:
            colunas_ausentes.append('Salario mensal')

        if len(colunas_ausentes) == 3:
            return jsonify({
                'mensagem': 'Nenhuma coluna reconhecida. Use CPF, Nome completo e Salario mensal.'
            }), 400

        cursor = con.cursor()

        itens = []
        cpfs_arquivo = set()
        novos = 0
        existentes = 0
        erros = 0

        for numero_linha, linha in enumerate(leitor, start=2):
            if not any(str(valor or '').strip() for valor in linha.values() if not isinstance(valor, list)):
                continue

            cpf = normalizar_cpf(linha.get(campo_cpf)) if campo_cpf else ''
            nome = str(linha.get(campo_nome) or '').strip() if campo_nome else ''
            salario_original = linha.get(campo_salario) if campo_salario else None

            item = {
                'linha': numero_linha,
                'cpf': cpf,
                'cpf_valido': False,
                'nome': nome,
                'salario': None,
                'situacao': None,
                'erro': None,
                'possui_usuario_arkhe': False,
                'possui_conta_arkhe': False
            }

            problemas = []

            if not campo_cpf or not cpf:
                problemas.append('CPF nao informado')
            elif len(cpf) != 11:
                problemas.append('CPF deve possuir 11 digitos')
            elif not validar_cpf(cpf):
                problemas.append('CPF invalido')
            else:
                item['cpf_valido'] = True
                if cpf in cpfs_arquivo:
                    problemas.append('CPF duplicado no arquivo')
                else:
                    cpfs_arquivo.add(cpf)

            if not campo_nome or not nome:
                problemas.append('Nome nao informado')

            if not campo_salario or salario_original is None or not str(salario_original).strip():
                problemas.append('Salario nao informado')
            else:
                try:
                    salario = converter_salario(salario_original)
                    item['salario'] = float(salario)
                except (InvalidOperation, ValueError):
                    problemas.append('Salario invalido')

            if problemas:
                itens.append(erro_item(item, problemas))
                erros += 1
                continue

            cursor.execute(
                "SELECT ID_FUNCIONARIO, NOME, SALARIO, STATUS FROM FUNCIONARIO WHERE ID_CONTA_EMPRESA = ? AND CPF = ?",
                (id_conta, cpf)
            )
            funcionario = cursor.fetchone()

            cursor.execute(
                """SELECT U.ID_USUARIO, C.ID_CONTA
                   FROM USUARIO U
                   LEFT JOIN CONTA C ON C.ID_USUARIO = U.ID_USUARIO AND C.TIPO_CONTA = 0
                   WHERE U.CPF = ?
                   ORDER BY C.ID_CONTA NULLS LAST ROWS 1""",
                (cpf,)
            )
            conta_arkhe = cursor.fetchone()

            item['possui_usuario_arkhe'] = conta_arkhe is not None
            item['possui_conta_arkhe'] = bool(conta_arkhe and conta_arkhe[1] is not None)

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

        if not itens:
            return jsonify({'mensagem': 'O CSV nao possui linhas de funcionarios para analisar'}), 400

        return jsonify({
            'mensagem': 'CSV analisado com sucesso',
            'total_linhas': len(itens),
            'novos': novos,
            'existentes': existentes,
            'erros': erros,
            'colunas_ausentes': colunas_ausentes,
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
            cpf = normalizar_cpf(item.get('cpf'))
            nome = str(item.get('nome') or '').strip()
            salario_original = item.get('salario')
            acao = item.get('acao')
            linha_item = item.get('linha', indice + 1)

            if acao not in ('criar', 'atualizar', 'ignorar'):
                erros.append({
                    'linha': linha_item,
                    'cpf': cpf,
                    'erro': 'Acao invalida'
                })
                continue

            if cpf and cpf in cpfs_importacao:
                erros.append({
                    'linha': linha_item,
                    'cpf': cpf,
                    'erro': 'CPF duplicado na importacao'
                })
                continue

            if cpf:
                cpfs_importacao.add(cpf)

            if acao == 'ignorar':
                ignorados += 1
                continue

            problemas = []

            if not cpf:
                problemas.append('CPF nao informado')
            elif not validar_cpf(cpf):
                problemas.append('CPF invalido')

            if not nome:
                problemas.append('Nome nao informado')

            try:
                salario = converter_salario(salario_original)
            except (InvalidOperation, ValueError):
                salario = None
                problemas.append('Salario invalido' if salario_original not in (None, '') else 'Salario nao informado')

            if problemas:
                erros.append({
                    'linha': linha_item,
                    'cpf': cpf,
                    'erro': '; '.join(problemas)
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
