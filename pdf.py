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
            UP.CNPJ,
            UP.NOME_FANTASIA,
            UP.RAZAO_SOCIAL,

            CR.NUMERO_CONTA,
            CR.AGENCIA,
            CR.BANCO,
            CR.TIPO_CONTA,

            UR.NOME,
            UR.CPF,
            UR.CNPJ,
            UR.NOME_FANTASIA,
            UR.RAZAO_SOCIAL

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


def descobrir_tipo_movimentacao(id_pagador, valor, id_cobranca):
    if id_cobranca is not None:
        return 'Pagamento de boleto'

    if id_pagador == 9 and float(valor) == 5000:
        return 'Credito inicial'

    return 'Pix'


def linha_comprovante(pdf, y, titulo, valor):
    pdf.setFont('Helvetica', 7)
    pdf.setFillColor(HexColor('#666666'))
    pdf.drawString(25 * mm, y, titulo.upper())

    pdf.setFont('Helvetica-Bold', 10)
    pdf.setFillColor(black)
    pdf.drawString(25 * mm, y - 5 * mm, texto_limitado(valor, 75))

    pdf.setStrokeColor(HexColor('#E5E5E5'))
    pdf.setLineWidth(0.4)
    pdf.line(25 * mm, y - 9 * mm, 185 * mm, y - 9 * mm)


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
                          UP.CNPJ,
                          UP.NOME_FANTASIA,
                          UP.RAZAO_SOCIAL,

                          CR.NUMERO_CONTA,
                          CR.AGENCIA,
                          CR.BANCO,
                          CR.TIPO_CONTA,

                          UR.NOME,
                          UR.CPF,
                          UR.CNPJ,
                          UR.NOME_FANTASIA,
                          UR.RAZAO_SOCIAL,

                          COB.CODIGO_PAGAMENTO

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
            id_cobranca
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

        pdf.setFillColor(HexColor('#073E3E'))
        pdf.rect(
            0,
            240 * mm,
            210 * mm,
            57 * mm,
            stroke=0,
            fill=1
        )

        pdf.setFillColor(HexColor('#FFFFFF'))

        pdf.setFont(
            'Helvetica-Bold',
            24
        )

        pdf.drawString(
            25 * mm,
            277 * mm,
            'ARKHÉ'
        )

        pdf.setFont(
            'Helvetica',
            8
        )

        pdf.drawString(
            25 * mm,
            270 * mm,
            'BANCO DIGITAL DIDATICO'
        )

        pdf.setFont(
            'Helvetica-Bold',
            13
        )

        pdf.drawRightString(
            185 * mm,
            277 * mm,
            'COMPROVANTE'
        )

        pdf.setFillColor(
            HexColor('#147D64')
        )

        pdf.circle(
            105 * mm,
            228 * mm,
            12 * mm,
            stroke=0,
            fill=1
        )

        pdf.setFillColor(
            HexColor('#FFFFFF')
        )

        pdf.setFont(
            'Helvetica-Bold',
            12
        )

        pdf.drawCentredString(
            105 * mm,
            226 * mm,
            'OK'
        )

        pdf.setFillColor(
            HexColor('#147D64')
        )

        pdf.setFont(
            'Helvetica-Bold',
            10
        )

        pdf.drawCentredString(
            105 * mm,
            209 * mm,
            'PAGAMENTO CONCLUIDO'
        )

        pdf.setFillColor(
            HexColor('#111111')
        )

        pdf.setFont(
            'Helvetica-Bold',
            25
        )

        pdf.drawCentredString(
            105 * mm,
            194 * mm,
            formatar_moeda(valor)
        )

        pdf.setFont(
            'Helvetica',
            8
        )

        pdf.setFillColor(
            HexColor('#666666')
        )

        pdf.drawCentredString(
            105 * mm,
            185 * mm,
            tipo_movimentacao
        )

        linha_comprovante(
            pdf,
            168 * mm,
            'Data e hora',
            formatar_data_hora(data_movimentacao)
        )

        linha_comprovante(
            pdf,
            150 * mm,
            'Pagador',
            pagador
        )

        linha_comprovante(
            pdf,
            132 * mm,
            'CPF / CNPJ do pagador',
            documento_pagador
        )

        linha_comprovante(
            pdf,
            114 * mm,
            'Conta de origem',
            f'{banco_pagador} - Agencia {agencia_pagador} - Conta {numero_conta_pagador}'
        )

        linha_comprovante(
            pdf,
            96 * mm,
            'Recebedor',
            recebedor
        )

        linha_comprovante(
            pdf,
            78 * mm,
            'CPF / CNPJ do recebedor',
            documento_recebedor
        )

        linha_comprovante(
            pdf,
            60 * mm,
            'Conta de destino',
            f'{banco_recebedor} - Agencia {agencia_recebedor} - Conta {numero_conta_recebedor}'
        )

        pdf.setFont(
            'Helvetica',
            7
        )

        pdf.setFillColor(
            HexColor('#666666')
        )

        pdf.drawString(
            25 * mm,
            42 * mm,
            'IDENTIFICACAO DA TRANSACAO'
        )

        pdf.setFont(
            'Helvetica-Bold',
            9
        )

        pdf.setFillColor(
            black
        )

        pdf.drawString(
            25 * mm,
            36 * mm,
            f'ARKHE-{str(id_movimentacao).zfill(12)}'
        )

        if id_cobranca is not None:
            pdf.setFont(
                'Helvetica',
                7
            )

            pdf.setFillColor(
                HexColor('#666666')
            )

            pdf.drawRightString(
                185 * mm,
                42 * mm,
                'COBRANCA'
            )

            pdf.setFont(
                'Helvetica-Bold',
                9
            )

            pdf.setFillColor(
                black
            )

            pdf.drawRightString(
                185 * mm,
                36 * mm,
                f'#{id_cobranca}'
            )

        if codigo_pagamento:
            pdf.setFont(
                'Helvetica',
                6.5
            )

            pdf.setFillColor(
                HexColor('#666666')
            )

            pdf.drawString(
                25 * mm,
                27 * mm,
                f'Codigo do boleto: {codigo_pagamento}'
            )

        pdf.setStrokeColor(
            HexColor('#DDDDDD')
        )

        pdf.line(
            25 * mm,
            20 * mm,
            185 * mm,
            20 * mm
        )

        pdf.setFont(
            'Helvetica',
            6
        )

        pdf.setFillColor(
            HexColor('#777777')
        )

        pdf.drawCentredString(
            105 * mm,
            14 * mm,
            'Comprovante gerado pelo Banco Arkhé'
        )

        pdf.drawCentredString(
            105 * mm,
            10 * mm,
            'Documento interno do ambiente didatico Arkhé'
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