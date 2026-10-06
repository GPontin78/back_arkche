from flask import jsonify, send_file
from main import app
from banco import con
from funcao import descobre_id_conta
from io import BytesIO
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, black
from reportlab.graphics.barcode import code128


def formatar_moeda(valor):
    valor = float(valor or 0)
    texto = f'{valor:,.2f}'
    texto = texto.replace(',', 'X').replace('.', ',').replace('X', '.')
    return 'R$ ' + texto


def somente_numeros(valor):
    return ''.join(numero for numero in str(valor or '') if numero.isdigit())


def formatar_cpf(valor):
    valor = somente_numeros(valor)

    if len(valor) != 11:
        return valor

    return f'{valor[:3]}.{valor[3:6]}.{valor[6:9]}-{valor[9:]}'


def formatar_cnpj(valor):
    valor = somente_numeros(valor)

    if len(valor) != 14:
        return valor

    return f'{valor[:2]}.{valor[2:5]}.{valor[5:8]}/{valor[8:12]}-{valor[12:]}'


def formatar_documento(cpf, cnpj):
    if cnpj:
        return formatar_cnpj(cnpj)

    return formatar_cpf(cpf)


def formatar_data(valor):
    if not valor:
        return '-'

    if hasattr(valor, 'strftime'):
        return valor.strftime('%d/%m/%Y')

    texto = str(valor)

    for formato in ['%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%d/%m/%Y']:
        try:
            return datetime.strptime(texto, formato).strftime('%d/%m/%Y')
        except ValueError:
            pass

    return texto


def nome_cliente(nome, nome_fantasia, razao_social, tipo_conta):
    if tipo_conta == 1:
        return nome_fantasia or razao_social or nome or '-'

    return nome or '-'


def texto_limitado(texto, limite):
    texto = str(texto or '-')

    if len(texto) > limite:
        return texto[:limite - 3] + '...'

    return texto


def campo(pdf, x, y, largura, altura, titulo, valor, tamanho=9, negrito=False):
    pdf.setStrokeColor(HexColor('#222222'))
    pdf.setLineWidth(0.35)
    pdf.rect(x, y, largura, altura, stroke=1, fill=0)

    pdf.setFont('Helvetica', 5.8)
    pdf.setFillColor(HexColor('#555555'))
    pdf.drawString(x + 2 * mm, y + altura - 3.3 * mm, titulo.upper())

    pdf.setFillColor(black)

    if negrito:
        pdf.setFont('Helvetica-Bold', tamanho)
    else:
        pdf.setFont('Helvetica', tamanho)

    pdf.drawString(
        x + 2 * mm,
        y + 3.1 * mm,
        texto_limitado(valor, 80)
    )


def linha_tracejada(pdf, y):
    pdf.saveState()
    pdf.setStrokeColor(HexColor('#777777'))
    pdf.setDash(3, 3)
    pdf.line(15 * mm, y, 195 * mm, y)
    pdf.restoreState()

    pdf.setFont('Helvetica', 5.5)
    pdf.setFillColor(HexColor('#777777'))
    pdf.drawString(15 * mm, y + 2 * mm, 'RECORTE NA LINHA PONTILHADA')


def desenhar_marca_interna(pdf):
    pdf.saveState()
    pdf.setFillColor(HexColor('#EAEAEA'))
    pdf.setFont('Helvetica-Bold', 29)

    pdf.translate(55 * mm, 135 * mm)
    pdf.rotate(35)

    pdf.drawString(
        0,
        0,
        'DOCUMENTO INTERNO ARKHÉ'
    )

    pdf.restoreState()


def desenhar_cabecalho(pdf, titulo):
    pdf.setFillColor(HexColor('#111111'))

    pdf.setFont('Helvetica-Bold', 23)
    pdf.drawString(15 * mm, 277 * mm, 'ARKHÉ')

    pdf.setFont('Helvetica-Bold', 7)
    pdf.drawString(15 * mm, 271.5 * mm, 'BANCO DIGITAL DIDÁTICO')

    pdf.setFont('Helvetica-Bold', 11)
    pdf.drawRightString(195 * mm, 277 * mm, titulo)

    pdf.setFont('Helvetica', 6)
    pdf.setFillColor(HexColor('#555555'))
    pdf.drawRightString(
        195 * mm,
        271.5 * mm,
        'DOCUMENTO INTERNO • SEM VALIDADE NO SISTEMA BANCÁRIO NACIONAL'
    )

    pdf.setStrokeColor(HexColor('#111111'))
    pdf.setLineWidth(1)
    pdf.line(15 * mm, 267 * mm, 195 * mm, 267 * mm)


def desenhar_codigo_barras(pdf, codigo, x, y, largura_maxima):
    codigo = str(codigo)

    barras = code128.Code128(
        codigo,
        barHeight=17 * mm,
        barWidth=0.42 * mm,
        humanReadable=False
    )

    if barras.width > largura_maxima:
        escala = largura_maxima / barras.width

        pdf.saveState()
        pdf.translate(x, y)
        pdf.scale(escala, 1)
        barras.drawOn(pdf, 0, 0)
        pdf.restoreState()
    else:
        posicao_x = x + ((largura_maxima - barras.width) / 2)
        barras.drawOn(pdf, posicao_x, y)


def linha_referencia(codigo, vencimento, valor):
    codigo = str(codigo or '')
    codigo = somente_numeros(codigo)

    vencimento_texto = ''

    if hasattr(vencimento, 'strftime'):
        vencimento_texto = vencimento.strftime('%Y%m%d')
    else:
        try:
            vencimento_texto = datetime.strptime(
                str(vencimento),
                '%Y-%m-%d'
            ).strftime('%Y%m%d')
        except Exception:
            vencimento_texto = somente_numeros(vencimento)

    centavos = int(round(float(valor or 0) * 100))

    return f'{codigo}  {vencimento_texto}  {str(centavos).zfill(12)}'


@app.route('/boleto_pdf/<int:id_cobranca>', methods=['GET'])
def boleto_pdf(id_cobranca):
    id_conta = descobre_id_conta()

    if not id_conta:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = con.cursor()

    cursor.execute("""
        SELECT
            COB.ID_COBRANCA,
            COB.ID_PAGADOR,
            COB.ID_RECEBEDOR,
            COB.VALOR,
            COB.DATA_VENCIMENTO,
            COB.CODIGO_PAGAMENTO,
            COB.STATUS,

            CP.NUMERO_CONTA,
            CP.AGENCIA,
            CP.BANCO,
            CP.TIPO_CONTA,

            UP.NOME,
            UP.CPF,
            CP.CNPJ,
            CP.NOME_FANTASIA,
            CP.RAZAO_SOCIAL,

            CR.NUMERO_CONTA,
            CR.AGENCIA,
            CR.BANCO,
            CR.TIPO_CONTA,

            UR.NOME,
            UR.CPF,
            CR.CNPJ,
            CR.NOME_FANTASIA,
            CR.RAZAO_SOCIAL

        FROM COBRANCA COB

        INNER JOIN CONTA CP
        ON CP.ID_CONTA = COB.ID_PAGADOR

        INNER JOIN USUARIO UP
        ON UP.ID_USUARIO = CP.ID_USUARIO

        INNER JOIN CONTA CR
        ON CR.ID_CONTA = COB.ID_RECEBEDOR

        INNER JOIN USUARIO UR
        ON UR.ID_USUARIO = CR.ID_USUARIO

        WHERE COB.ID_COBRANCA = ?
        AND COB.TIPO_COBRANCA = 0
    """, (id_cobranca,))


    boleto = cursor.fetchone()
    cursor.close()

    if not boleto:
        return jsonify({'mensagem': 'Boleto nao encontrado'}), 404

    id_pagador = boleto[1]
    id_recebedor = boleto[2]

    if id_conta != id_pagador and id_conta != id_recebedor:
        return jsonify({'mensagem': 'Voce nao possui acesso a este boleto'}), 403

    valor = boleto[3]
    vencimento = boleto[4]
    codigo_pagamento = boleto[5]
    status = boleto[6]

    numero_conta_pagador = boleto[7]
    agencia_pagador = boleto[8]
    banco_pagador = boleto[9]
    tipo_conta_pagador = boleto[10]

    nome_pagador = boleto[11]
    cpf_pagador = boleto[12]
    cnpj_pagador = boleto[13]
    nome_fantasia_pagador = boleto[14]
    razao_social_pagador = boleto[15]

    numero_conta_recebedor = boleto[16]
    agencia_recebedor = boleto[17]
    banco_recebedor = boleto[18]
    tipo_conta_recebedor = boleto[19]

    nome_recebedor = boleto[20]
    cpf_recebedor = boleto[21]
    cnpj_recebedor = boleto[22]
    nome_fantasia_recebedor = boleto[23]
    razao_social_recebedor = boleto[24]

    pagador = nome_cliente(
        nome_pagador,
        nome_fantasia_pagador,
        razao_social_pagador,
        tipo_conta_pagador
    )

    recebedor = nome_cliente(
        nome_recebedor,
        nome_fantasia_recebedor,
        razao_social_recebedor,
        tipo_conta_recebedor
    )

    documento_pagador = formatar_documento(
        cpf_pagador,
        cnpj_pagador
    )

    documento_recebedor = formatar_documento(
        cpf_recebedor,
        cnpj_recebedor
    )

    referencia = linha_referencia(
        codigo_pagamento,
        vencimento,
        valor
    )

    memoria = BytesIO()

    pdf = canvas.Canvas(
        memoria,
        pagesize=A4
    )

    pdf.setTitle(
        f'Boleto Arkhé #{id_cobranca}'
    )

    pdf.setAuthor('Banco Arkhé')

    desenhar_marca_interna(pdf)

    desenhar_cabecalho(
        pdf,
        'RECIBO DO PAGADOR'
    )

    x = 15 * mm
    largura = 180 * mm

    campo(
        pdf,
        x,
        248 * mm,
        115 * mm,
        15 * mm,
        'Beneficiário',
        recebedor,
        9,
        True
    )

    campo(
        pdf,
        130 * mm,
        248 * mm,
        65 * mm,
        15 * mm,
        'CPF / CNPJ do beneficiário',
        documento_recebedor,
        8
    )

    campo(
        pdf,
        x,
        232 * mm,
        45 * mm,
        15 * mm,
        'Agência',
        agencia_recebedor,
        9
    )

    campo(
        pdf,
        60 * mm,
        232 * mm,
        55 * mm,
        15 * mm,
        'Conta',
        numero_conta_recebedor,
        9
    )

    campo(
        pdf,
        115 * mm,
        232 * mm,
        40 * mm,
        15 * mm,
        'Vencimento',
        formatar_data(vencimento),
        9,
        True
    )

    campo(
        pdf,
        155 * mm,
        232 * mm,
        40 * mm,
        15 * mm,
        'Valor',
        formatar_moeda(valor),
        9,
        True
    )

    campo(
        pdf,
        x,
        216 * mm,
        115 * mm,
        15 * mm,
        'Pagador',
        pagador,
        9,
        True
    )

    campo(
        pdf,
        130 * mm,
        216 * mm,
        65 * mm,
        15 * mm,
        'CPF / CNPJ do pagador',
        documento_pagador,
        8
    )

    campo(
        pdf,
        x,
        200 * mm,
        60 * mm,
        15 * mm,
        'Número do documento',
        str(id_cobranca).zfill(10),
        9
    )

    campo(
        pdf,
        75 * mm,
        200 * mm,
        80 * mm,
        15 * mm,
        'Código de pagamento interno',
        codigo_pagamento,
        9,
        True
    )

    campo(
        pdf,
        155 * mm,
        200 * mm,
        40 * mm,
        15 * mm,
        'Situação',
        'PAGO' if status == 1 else 'PENDENTE',
        8,
        True
    )

    pdf.setFont('Helvetica', 6)
    pdf.setFillColor(HexColor('#555555'))

    pdf.drawString(
        17 * mm,
        192 * mm,
        'Este documento representa uma cobrança interna entre contas do ecossistema Banco Arkhé.'
    )

    pdf.drawString(
        17 * mm,
        188 * mm,
        'O pagamento é processado exclusivamente pela plataforma Arkhé.'
    )

    linha_tracejada(
        pdf,
        178 * mm
    )

    pdf.setFillColor(black)

    pdf.setFont(
        'Helvetica-Bold',
        20
    )

    pdf.drawString(
        15 * mm,
        164 * mm,
        'ARKHÉ'
    )

    pdf.setFont(
        'Helvetica-Bold',
        11
    )

    pdf.drawRightString(
        195 * mm,
        164 * mm,
        'FICHA DE PAGAMENTO INTERNA'
    )

    pdf.setLineWidth(1)

    pdf.line(
        15 * mm,
        159 * mm,
        195 * mm,
        159 * mm
    )

    campo(
        pdf,
        15 * mm,
        142 * mm,
        115 * mm,
        15 * mm,
        'Beneficiário',
        recebedor,
        9,
        True
    )

    campo(
        pdf,
        130 * mm,
        142 * mm,
        65 * mm,
        15 * mm,
        'CPF / CNPJ',
        documento_recebedor,
        8
    )

    campo(
        pdf,
        15 * mm,
        126 * mm,
        35 * mm,
        15 * mm,
        'Banco',
        banco_recebedor,
        8
    )

    campo(
        pdf,
        50 * mm,
        126 * mm,
        40 * mm,
        15 * mm,
        'Agência',
        agencia_recebedor,
        8
    )

    campo(
        pdf,
        90 * mm,
        126 * mm,
        45 * mm,
        15 * mm,
        'Conta',
        numero_conta_recebedor,
        8
    )

    campo(
        pdf,
        135 * mm,
        126 * mm,
        30 * mm,
        15 * mm,
        'Vencimento',
        formatar_data(vencimento),
        8,
        True
    )

    campo(
        pdf,
        165 * mm,
        126 * mm,
        30 * mm,
        15 * mm,
        'Valor',
        formatar_moeda(valor),
        8,
        True
    )

    campo(
        pdf,
        15 * mm,
        110 * mm,
        115 * mm,
        15 * mm,
        'Pagador',
        pagador,
        9,
        True
    )

    campo(
        pdf,
        130 * mm,
        110 * mm,
        65 * mm,
        15 * mm,
        'CPF / CNPJ',
        documento_pagador,
        8
    )

    campo(
        pdf,
        15 * mm,
        94 * mm,
        60 * mm,
        15 * mm,
        'Agência / Conta do pagador',
        f'{agencia_pagador} / {numero_conta_pagador}',
        8
    )

    campo(
        pdf,
        75 * mm,
        94 * mm,
        120 * mm,
        15 * mm,
        'Referência interna Arkhé',
        referencia,
        7,
        True
    )

    pdf.setFont(
        'Helvetica-Bold',
        6
    )

    pdf.setFillColor(
        HexColor('#444444')
    )

    pdf.drawString(
        15 * mm,
        88 * mm,
        'INSTRUÇÕES'
    )

    pdf.setFont(
        'Helvetica',
        6.3
    )

    pdf.drawString(
        15 * mm,
        83.5 * mm,
        'Pagamento disponível exclusivamente através dos canais internos do Banco Arkhé.'
    )

    pdf.drawString(
        15 * mm,
        79.5 * mm,
        'Utilize o código abaixo para localizar esta cobrança no aplicativo.'
    )

    pdf.drawString(
        15 * mm,
        75.5 * mm,
        'Após o pagamento, o status da cobrança será atualizado automaticamente.'
    )

    pdf.setFillColor(
        black
    )

    desenhar_codigo_barras(
        pdf,
        codigo_pagamento,
        20 * mm,
        46 * mm,
        170 * mm
    )

    pdf.setFont(
        'Helvetica-Bold',
        9
    )

    pdf.drawCentredString(
        105 * mm,
        40 * mm,
        str(codigo_pagamento)
    )

    pdf.setFont(
        'Helvetica',
        6
    )

    pdf.setFillColor(
        HexColor('#555555')
    )

    pdf.drawCentredString(
        105 * mm,
        35 * mm,
        'CÓDIGO DE BARRAS PARA LEITURA EXCLUSIVA PELO SISTEMA ARKHÉ'
    )

    pdf.setStrokeColor(
        HexColor('#111111')
    )

    pdf.line(
        15 * mm,
        29 * mm,
        195 * mm,
        29 * mm
    )

    pdf.setFont(
        'Helvetica-Bold',
        6.5
    )

    pdf.drawCentredString(
        105 * mm,
        24 * mm,
        'DOCUMENTO INTERNO ARKHÉ — SEM VALIDADE NO SISTEMA BANCÁRIO NACIONAL'
    )

    pdf.setFont(
        'Helvetica',
        5.5
    )

    pdf.drawCentredString(
        105 * mm,
        19.5 * mm,
        f'Cobrança #{id_cobranca} • Referência {codigo_pagamento}'
    )

    pdf.save()

    memoria.seek(0)

    return send_file(
        memoria,
        mimetype='application/pdf',
        as_attachment=False,
        download_name=f'boleto_arkhe_{id_cobranca}.pdf'
    )


def formatar_data_hora(valor):
    if not valor:
        return '-'

    if hasattr(valor, 'strftime'):
        return valor.strftime('%d/%m/%Y as %H:%M:%S')

    texto = str(valor)

    for formato in ['%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d']:
        try:
            return datetime.strptime(texto, formato).strftime('%d/%m/%Y as %H:%M:%S')
        except ValueError:
            pass

    return texto


def descobrir_tipo_movimentacao(id_pagador, valor, id_cobranca, tipo_cobranca):
    if id_pagador == 9 and float(valor) == 5000:
        return 'Credito inicial'

    if id_cobranca is not None and tipo_cobranca == 0:
        return 'Pagamento de boleto'

    if id_cobranca is not None and tipo_cobranca == 1:
        return 'Pix via QR Code'

    return 'Pix'


def titulo_comprovante(tipo_movimentacao):
    if tipo_movimentacao == 'Pagamento de boleto':
        return 'COMPROVANTE DE PAGAMENTO'

    if tipo_movimentacao == 'Credito inicial':
        return 'COMPROVANTE DE CREDITO'

    return 'COMPROVANTE DE PIX'


def campo_comprovante(pdf, x, y, titulo, valor, limite=54):
    pdf.setFillColor(HexColor('#667085'))
    pdf.setFont('Helvetica-Bold', 6.5)
    pdf.drawString(x, y, titulo.upper())

    pdf.setFillColor(HexColor('#111111'))
    pdf.setFont('Helvetica-Bold', 9.5)
    pdf.drawString(
        x,
        y - 5 * mm,
        texto_limitado(valor, limite)
    )


@app.route('/comprovante/<int:id_movimentacao>', methods=['GET'])
def comprovante(id_movimentacao):
    id_conta = descobre_id_conta()

    if not id_conta:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("""SELECT
                          M.ID_MOVIMENTACAO,
                          M.ID_PAGADOR,
                          M.ID_RECEBEDOR,
                          M.VALOR,
                          M.DATA_MOVIMENTACAO,
                          M.ID_COBRANCA,

                          CP.NUMERO_CONTA,
                          CP.AGENCIA,
                          CP.BANCO,
                          CP.TIPO_CONTA,

                          UP.NOME,
                          UP.CPF,
                          CP.CNPJ,
                          CP.NOME_FANTASIA,
                          CP.RAZAO_SOCIAL,

                          CR.NUMERO_CONTA,
                          CR.AGENCIA,
                          CR.BANCO,
                          CR.TIPO_CONTA,

                          UR.NOME,
                          UR.CPF,
                          CR.CNPJ,
                          CR.NOME_FANTASIA,
                          CR.RAZAO_SOCIAL,

                          COB.CODIGO_PAGAMENTO,
                          COB.TIPO_COBRANCA

                          FROM MOVIMENTACAO M
                          INNER JOIN CONTA CP ON CP.ID_CONTA = M.ID_PAGADOR
                          INNER JOIN USUARIO UP ON UP.ID_USUARIO = CP.ID_USUARIO
                          INNER JOIN CONTA CR ON CR.ID_CONTA = M.ID_RECEBEDOR
                          INNER JOIN USUARIO UR ON UR.ID_USUARIO = CR.ID_USUARIO
                          LEFT JOIN COBRANCA COB ON COB.ID_COBRANCA = M.ID_COBRANCA
                          WHERE M.ID_MOVIMENTACAO = ?""",
                       (id_movimentacao,))

        
        movimentacao = cursor.fetchone()

        if not movimentacao:
            return jsonify({'mensagem': 'Movimentacao nao encontrada'}), 404

        id_pagador = movimentacao[1]

        if id_pagador != id_conta:
            return jsonify({'mensagem': 'Este comprovante pertence a outra conta'}), 403

        id_recebedor = movimentacao[2]
        valor = movimentacao[3]
        data_movimentacao = movimentacao[4]
        id_cobranca = movimentacao[5]

        numero_conta_pagador = movimentacao[6]
        agencia_pagador = movimentacao[7]
        banco_pagador = movimentacao[8]
        tipo_conta_pagador = movimentacao[9]

        nome_pagador = movimentacao[10]
        cpf_pagador = movimentacao[11]
        cnpj_pagador = movimentacao[12]
        nome_fantasia_pagador = movimentacao[13]
        razao_social_pagador = movimentacao[14]

        numero_conta_recebedor = movimentacao[15]
        agencia_recebedor = movimentacao[16]
        banco_recebedor = movimentacao[17]
        tipo_conta_recebedor = movimentacao[18]

        nome_recebedor = movimentacao[19]
        cpf_recebedor = movimentacao[20]
        cnpj_recebedor = movimentacao[21]
        nome_fantasia_recebedor = movimentacao[22]
        razao_social_recebedor = movimentacao[23]

        codigo_pagamento = movimentacao[24]
        tipo_cobranca = movimentacao[25]

        pagador = nome_cliente(
            nome_pagador,
            nome_fantasia_pagador,
            razao_social_pagador,
            tipo_conta_pagador
        )

        recebedor = nome_cliente(
            nome_recebedor,
            nome_fantasia_recebedor,
            razao_social_recebedor,
            tipo_conta_recebedor
        )

        documento_pagador = formatar_documento(
            cpf_pagador,
            cnpj_pagador
        )

        documento_recebedor = formatar_documento(
            cpf_recebedor,
            cnpj_recebedor
        )

        tipo_movimentacao = descobrir_tipo_movimentacao(
            id_pagador,
            valor,
            id_cobranca,
            tipo_cobranca
        )

        memoria = BytesIO()

        pdf = canvas.Canvas(
            memoria,
            pagesize=A4
        )

        pdf.setTitle(
            f'Comprovante Arkhé #{id_movimentacao}'
        )

        pdf.setAuthor('Banco Arkhé')

        titulo_documento = titulo_comprovante(tipo_movimentacao)

        pdf.setFillColor(HexColor('#FFFFFF'))
        pdf.rect(
            0,
            0,
            210 * mm,
            297 * mm,
            stroke=0,
            fill=1
        )

        pdf.setFillColor(HexColor('#111111'))
        pdf.setFont('Helvetica-Bold', 23)
        pdf.drawString(15 * mm, 277 * mm, 'ARKHÉ')

        pdf.setFont('Helvetica-Bold', 7)
        pdf.drawString(15 * mm, 271.5 * mm, 'BANCO DIGITAL DIDÁTICO')

        pdf.setFont('Helvetica-Bold', 11)
        pdf.drawRightString(195 * mm, 277 * mm, titulo_documento)

        pdf.setFont('Helvetica', 6)
        pdf.setFillColor(HexColor('#667085'))
        pdf.drawRightString(
            195 * mm,
            271.5 * mm,
            'DOCUMENTO INTERNO • BANCO ARKHÉ'
        )

        pdf.setStrokeColor(HexColor('#111111'))
        pdf.setLineWidth(1)
        pdf.line(15 * mm, 267 * mm, 195 * mm, 267 * mm)

        pdf.setFillColor(HexColor('#F3FAF7'))
        pdf.roundRect(
            15 * mm,
            244 * mm,
            180 * mm,
            17 * mm,
            3 * mm,
            stroke=0,
            fill=1
        )

        pdf.setFillColor(HexColor('#147D64'))
        pdf.circle(
            24 * mm,
            252.5 * mm,
            2.2 * mm,
            stroke=0,
            fill=1
        )

        pdf.setFont('Helvetica-Bold', 8)
        pdf.drawString(
            30 * mm,
            250.2 * mm,
            'TRANSAÇÃO CONCLUÍDA'
        )

        pdf.setFillColor(HexColor('#667085'))
        pdf.setFont('Helvetica', 7)
        pdf.drawRightString(
            187 * mm,
            250.2 * mm,
            formatar_data_hora(data_movimentacao)
        )

        pdf.setStrokeColor(HexColor('#E4E7EC'))
        pdf.setLineWidth(0.7)
        pdf.roundRect(
            15 * mm,
            208 * mm,
            180 * mm,
            29 * mm,
            3 * mm,
            stroke=1,
            fill=0
        )

        pdf.setFillColor(HexColor('#667085'))
        pdf.setFont('Helvetica-Bold', 6.5)
        pdf.drawString(
            22 * mm,
            228 * mm,
            'VALOR DA TRANSAÇÃO'
        )

        pdf.setFillColor(HexColor('#111111'))
        pdf.setFont('Helvetica-Bold', 24)
        pdf.drawString(
            22 * mm,
            216 * mm,
            formatar_moeda(valor)
        )

        pdf.setFillColor(HexColor('#667085'))
        pdf.setFont('Helvetica', 8)
        pdf.drawRightString(
            187 * mm,
            216.8 * mm,
            tipo_movimentacao
        )

        pdf.setFillColor(HexColor('#111111'))
        pdf.setFont('Helvetica-Bold', 8)
        pdf.drawString(15 * mm, 194 * mm, 'ORIGEM')

        pdf.setStrokeColor(HexColor('#E4E7EC'))
        pdf.setLineWidth(0.5)
        pdf.line(15 * mm, 190 * mm, 195 * mm, 190 * mm)

        campo_comprovante(
            pdf,
            20 * mm,
            182 * mm,
            'Pagador',
            pagador
        )

        campo_comprovante(
            pdf,
            110 * mm,
            182 * mm,
            'CPF / CNPJ',
            documento_pagador
        )

        campo_comprovante(
            pdf,
            20 * mm,
            164 * mm,
            'Instituição',
            banco_pagador
        )

        campo_comprovante(
            pdf,
            110 * mm,
            164 * mm,
            'Agência / Conta',
            f'{agencia_pagador} / {numero_conta_pagador}'
        )

        pdf.setFillColor(HexColor('#111111'))
        pdf.setFont('Helvetica-Bold', 8)
        pdf.drawString(15 * mm, 145 * mm, 'DESTINO')

        pdf.setStrokeColor(HexColor('#E4E7EC'))
        pdf.line(15 * mm, 141 * mm, 195 * mm, 141 * mm)

        campo_comprovante(
            pdf,
            20 * mm,
            133 * mm,
            'Recebedor',
            recebedor
        )

        campo_comprovante(
            pdf,
            110 * mm,
            133 * mm,
            'CPF / CNPJ',
            documento_recebedor
        )

        campo_comprovante(
            pdf,
            20 * mm,
            115 * mm,
            'Instituição',
            banco_recebedor
        )

        campo_comprovante(
            pdf,
            110 * mm,
            115 * mm,
            'Agência / Conta',
            f'{agencia_recebedor} / {numero_conta_recebedor}'
        )

        pdf.setFillColor(HexColor('#F9FAFB'))
        pdf.roundRect(
            15 * mm,
            64 * mm,
            180 * mm,
            36 * mm,
            3 * mm,
            stroke=0,
            fill=1
        )

        pdf.setFillColor(HexColor('#111111'))
        pdf.setFont('Helvetica-Bold', 8)
        pdf.drawString(
            22 * mm,
            91 * mm,
            'DADOS DA TRANSAÇÃO'
        )

        pdf.setFillColor(HexColor('#667085'))
        pdf.setFont('Helvetica-Bold', 6.2)
        pdf.drawString(
            22 * mm,
            82 * mm,
            'IDENTIFICAÇÃO'
        )

        pdf.drawString(
            108 * mm,
            82 * mm,
            'TIPO'
        )

        pdf.setFillColor(HexColor('#111111'))
        pdf.setFont('Helvetica-Bold', 9)
        pdf.drawString(
            22 * mm,
            76 * mm,
            f'ARKHE-{str(id_movimentacao).zfill(12)}'
        )

        pdf.drawString(
            108 * mm,
            76 * mm,
            tipo_movimentacao
        )

        if codigo_pagamento:
            pdf.setFillColor(HexColor('#667085'))
            pdf.setFont('Helvetica', 7)

            if tipo_cobranca == 1:
                texto_codigo = f'Código Pix: {codigo_pagamento}'
            else:
                texto_codigo = f'Código do boleto: {codigo_pagamento}'

            pdf.drawString(
                22 * mm,
                69 * mm,
                texto_limitado(texto_codigo, 90)
            )
        elif id_cobranca is not None:
            pdf.setFillColor(HexColor('#667085'))
            pdf.setFont('Helvetica', 7)
            pdf.drawString(
                22 * mm,
                69 * mm,
                f'Cobrança interna #{id_cobranca}'
            )

        pdf.setStrokeColor(HexColor('#D0D5DD'))
        pdf.setLineWidth(0.5)
        pdf.line(
            15 * mm,
            42 * mm,
            195 * mm,
            42 * mm
        )

        pdf.setFillColor(HexColor('#667085'))
        pdf.setFont('Helvetica', 6)
        pdf.drawCentredString(
            105 * mm,
            34 * mm,
            'Comprovante gerado pelo Banco Arkhé'
        )

        pdf.drawCentredString(
            105 * mm,
            29.5 * mm,
            'Documento interno do ambiente didático Arkhé'
        )

        pdf.setFont('Helvetica-Bold', 6.2)
        pdf.drawCentredString(
            105 * mm,
            23.5 * mm,
            'SEM VALIDADE NO SISTEMA BANCÁRIO NACIONAL'
        )

        pdf.save()

        memoria.seek(0)

        return send_file(
            memoria,
            mimetype='application/pdf',
            as_attachment=False,
            download_name=f'comprovante_arkhe_{id_movimentacao}.pdf'
        )

    except Exception as e:
        print("ERRO:", e)
        return jsonify({'mensagem': 'Erro ao gerar comprovante'}), 500

    finally:
        if cursor:
            cursor.close()


def mascarar_cpf_relatorio(valor):
    cpf = somente_numeros(valor)

    if len(cpf) != 11:
        return '-'

    return '***.***.***-' + cpf[-2:]


def gerar_relatorio_funcionarios_pdf(id_conta):
    """Gera em memória o relatório de funcionários da conta PJ informada."""
    cursor = None

    try:
        cursor = con.cursor()
        cursor.execute(
            """SELECT C.CNPJ, C.NOME_FANTASIA, C.RAZAO_SOCIAL, U.NOME
               FROM CONTA C
               INNER JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
               WHERE C.ID_CONTA = ? AND C.TIPO_CONTA = 1""",
            (id_conta,)
        )
        empresa = cursor.fetchone()

        if not empresa:
            return None

        nome_empresa = empresa[1] or empresa[2] or empresa[3] or 'Empresa Arkhé'
        documento_empresa = formatar_cnpj(empresa[0]) if empresa[0] else '-'

        cursor.execute(
            """SELECT F.CPF, F.NOME, F.SALARIO, F.STATUS,
                      CASE WHEN EXISTS (
                          SELECT 1
                          FROM CONTA C
                          WHERE C.ID_USUARIO = F.ID_USUARIO
                            AND C.TIPO_CONTA = 0
                      ) THEN 1 ELSE 0 END AS POSSUI_CONTA_PF
               FROM FUNCIONARIO F
               WHERE F.ID_CONTA_EMPRESA = ?
               ORDER BY F.STATUS DESC, F.NOME""",
            (id_conta,)
        )
        funcionarios = cursor.fetchall()

        total_ativos = 0
        total_inativos = 0
        folha_mensal = 0.0

        for funcionario in funcionarios:
            if int(funcionario[3] or 0) == 1:
                total_ativos += 1
                folha_mensal += float(funcionario[2] or 0)
            else:
                total_inativos += 1

        memoria = BytesIO()
        pdf = canvas.Canvas(memoria, pagesize=A4)
        pdf.setTitle('Relatório de Funcionários - Banco Arkhé')
        pdf.setAuthor('Banco Arkhé')

        margem_x = 15 * mm
        largura_pagina = 210 * mm
        altura_pagina = 297 * mm
        largura_util = 180 * mm
        linhas_por_pagina = 22
        paginas = max(1, (len(funcionarios) + linhas_por_pagina - 1) // linhas_por_pagina)

        def cabecalho(numero_pagina):
            pdf.setFillColor(HexColor('#FFFFFF'))
            pdf.rect(0, 0, largura_pagina, altura_pagina, stroke=0, fill=1)

            pdf.setFillColor(HexColor('#111111'))
            pdf.setFont('Helvetica-Bold', 23)
            pdf.drawString(margem_x, 277 * mm, 'ARKHÉ')

            pdf.setFont('Helvetica-Bold', 7)
            pdf.drawString(margem_x, 271.5 * mm, 'BANCO DIGITAL DIDÁTICO')

            pdf.setFont('Helvetica-Bold', 11)
            pdf.drawRightString(195 * mm, 277 * mm, 'RELATÓRIO DE FUNCIONÁRIOS')

            pdf.setFont('Helvetica', 6)
            pdf.setFillColor(HexColor('#667085'))
            pdf.drawRightString(
                195 * mm,
                271.5 * mm,
                f'DOCUMENTO INTERNO • PÁGINA {numero_pagina} DE {paginas}'
            )

            pdf.setStrokeColor(HexColor('#111111'))
            pdf.setLineWidth(1)
            pdf.line(margem_x, 267 * mm, 195 * mm, 267 * mm)

        def rodape(numero_pagina):
            pdf.setStrokeColor(HexColor('#D0D5DD'))
            pdf.setLineWidth(0.5)
            pdf.line(margem_x, 18 * mm, 195 * mm, 18 * mm)

            pdf.setFillColor(HexColor('#667085'))
            pdf.setFont('Helvetica', 5.8)
            pdf.drawString(
                margem_x,
                12 * mm,
                'Relatório gerado pelo Banco Arkhé - ambiente didático.'
            )
            pdf.drawRightString(
                195 * mm,
                12 * mm,
                f'Página {numero_pagina} de {paginas}'
            )

        def cabecalho_tabela(y):
            pdf.setFillColor(HexColor('#F2F4F7'))
            pdf.roundRect(margem_x, y - 7 * mm, largura_util, 8 * mm, 1.5 * mm, stroke=0, fill=1)

            pdf.setFillColor(HexColor('#475467'))
            pdf.setFont('Helvetica-Bold', 6.2)
            pdf.drawString(18 * mm, y - 3.9 * mm, 'FUNCIONÁRIO')
            pdf.drawString(83 * mm, y - 3.9 * mm, 'CPF')
            pdf.drawRightString(145 * mm, y - 3.9 * mm, 'SALÁRIO')
            pdf.drawString(153 * mm, y - 3.9 * mm, 'STATUS')
            pdf.drawRightString(192 * mm, y - 3.9 * mm, 'CONTA ARKHÉ')

        for pagina in range(paginas):
            numero_pagina = pagina + 1
            cabecalho(numero_pagina)

            if pagina == 0:
                pdf.setFillColor(HexColor('#111111'))
                pdf.setFont('Helvetica-Bold', 12)
                pdf.drawString(margem_x, 255 * mm, texto_limitado(nome_empresa, 55))

                pdf.setFillColor(HexColor('#667085'))
                pdf.setFont('Helvetica', 6.5)
                pdf.drawString(margem_x, 249.5 * mm, f'CNPJ: {documento_empresa}')
                pdf.drawRightString(
                    195 * mm,
                    249.5 * mm,
                    'Gerado em ' + datetime.now().strftime('%d/%m/%Y às %H:%M')
                )

                cards = [
                    ('FUNCIONÁRIOS', str(len(funcionarios))),
                    ('ATIVOS', str(total_ativos)),
                    ('INATIVOS', str(total_inativos)),
                    ('FOLHA MENSAL ATIVA', formatar_moeda(folha_mensal))
                ]

                x_cards = [15, 58, 101, 144]
                larguras = [40, 40, 40, 51]

                for indice, card in enumerate(cards):
                    x = x_cards[indice] * mm
                    largura = larguras[indice] * mm

                    pdf.setStrokeColor(HexColor('#E4E7EC'))
                    pdf.setLineWidth(0.6)
                    pdf.roundRect(x, 226 * mm, largura, 17 * mm, 2.5 * mm, stroke=1, fill=0)

                    pdf.setFillColor(HexColor('#667085'))
                    pdf.setFont('Helvetica-Bold', 5.6)
                    pdf.drawString(x + 3 * mm, 237 * mm, card[0])

                    pdf.setFillColor(HexColor('#111111'))
                    pdf.setFont('Helvetica-Bold', 10)
                    pdf.drawString(x + 3 * mm, 230 * mm, card[1])

                y_tabela = 213 * mm
            else:
                pdf.setFillColor(HexColor('#111111'))
                pdf.setFont('Helvetica-Bold', 9)
                pdf.drawString(margem_x, 255 * mm, texto_limitado(nome_empresa, 70))

                pdf.setFillColor(HexColor('#667085'))
                pdf.setFont('Helvetica', 6)
                pdf.drawString(margem_x, 249.5 * mm, 'Continuação da relação de funcionários')
                y_tabela = 239 * mm

            cabecalho_tabela(y_tabela)
            y = y_tabela - 12 * mm

            inicio = pagina * linhas_por_pagina
            fim = inicio + linhas_por_pagina

            for indice, funcionario in enumerate(funcionarios[inicio:fim]):
                cpf, nome, salario, status, possui_conta = funcionario
                fundo = HexColor('#F9FAFB') if indice % 2 else HexColor('#FFFFFF')

                pdf.setFillColor(fundo)
                pdf.rect(margem_x, y - 4.8 * mm, largura_util, 7.5 * mm, stroke=0, fill=1)

                pdf.setFillColor(HexColor('#101828'))
                pdf.setFont('Helvetica', 7)
                pdf.drawString(18 * mm, y, texto_limitado(nome, 34))

                pdf.setFillColor(HexColor('#475467'))
                pdf.setFont('Helvetica', 6.7)
                pdf.drawString(83 * mm, y, mascarar_cpf_relatorio(cpf))

                pdf.setFillColor(HexColor('#101828'))
                pdf.setFont('Helvetica-Bold', 7)
                pdf.drawRightString(145 * mm, y, formatar_moeda(salario))

                status_texto = 'ATIVO' if int(status or 0) == 1 else 'INATIVO'
                pdf.setFont('Helvetica-Bold', 6.4)
                pdf.setFillColor(
                    HexColor('#147D64') if status_texto == 'ATIVO'
                    else HexColor('#667085')
                )
                pdf.drawString(153 * mm, y, status_texto)

                pdf.setFillColor(HexColor('#475467'))
                pdf.setFont('Helvetica-Bold', 6.4)
                pdf.drawRightString(
                    192 * mm,
                    y,
                    'SIM' if possui_conta else 'NÃO'
                )

                pdf.setStrokeColor(HexColor('#EAECF0'))
                pdf.setLineWidth(0.35)
                pdf.line(margem_x, y - 5.1 * mm, 195 * mm, y - 5.1 * mm)

                y -= 8 * mm

            if not funcionarios and pagina == 0:
                pdf.setFillColor(HexColor('#667085'))
                pdf.setFont('Helvetica', 9)
                pdf.drawCentredString(
                    105 * mm,
                    180 * mm,
                    'Nenhum funcionário cadastrado nesta empresa.'
                )

            rodape(numero_pagina)

            if numero_pagina < paginas:
                pdf.showPage()

        pdf.save()
        memoria.seek(0)

        return {
            'arquivo': memoria,
            'nome': 'relatorio_funcionarios_arkhe.pdf',
            'total_funcionarios': len(funcionarios),
            'ativos': total_ativos,
            'inativos': total_inativos,
            'folha_mensal_ativa': round(folha_mensal, 2)
        }

    finally:
        if cursor:
            cursor.close()
