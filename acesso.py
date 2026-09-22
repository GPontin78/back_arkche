from flask import jsonify, request
import datetime
from html import escape
from main import app
from banco import con
from funcao import (
    descobre_id_usuario,
    descobre_id_conta,
    criptografar_pin,
    gerar_pin_temporario,
    enviando_email,
    data_atual
)


CARGOS = {
    0: 'Administrativo',
    1: 'Financeiro',
    2: 'Contador',
    3: 'RH',
    4: 'Compras',
    5: 'Outro'
}

STATUS_ACESSO = {
    0: 'Pendente',
    1: 'Ativo',
    2: 'Bloqueado',
    3: 'Revogado'
}


def contexto_proprietario_pj():
    id_usuario = descobre_id_usuario()
    id_conta = descobre_id_conta()

    if not id_usuario or not id_conta:
        return None, (
            jsonify({'mensagem': 'Usuário não autenticado em uma conta'}),
            401
        )

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT ID_CONTA, ID_USUARIO, TIPO_CONTA,
                      CNPJ, NOME_FANTASIA, RAZAO_SOCIAL
               FROM CONTA
               WHERE ID_CONTA = ?""",
            (id_conta,)
        )

        conta = cursor.fetchone()

        if not conta:
            return None, (
                jsonify({'mensagem': 'Conta não encontrada'}),
                404
            )

        if conta[2] != 1:
            return None, (
                jsonify({'mensagem': 'Esta operação está disponível apenas para contas PJ'}),
                403
            )

        if conta[1] != id_usuario:
            return None, (
                jsonify({'mensagem': 'Somente o proprietário da conta PJ pode administrar os acessos'}),
                403
            )

        return {
            'id_conta': conta[0],
            'id_usuario': id_usuario,
            'cnpj': conta[3],
            'nome_fantasia': conta[4],
            'razao_social': conta[5]
        }, None

    finally:
        if cursor:
            cursor.close()


def nome_empresa(conta):
    return (
        conta.get('nome_fantasia')
        or conta.get('razao_social')
        or 'Empresa Arkhé'
    )


def validar_cargo(cargo):
    try:
        cargo = int(cargo)
    except (TypeError, ValueError):
        return None

    if cargo not in CARGOS:
        return None

    return cargo


def enviar_email_convite_existente(email, nome, empresa, cargo):
    url_login = 'https://arkhe-frontend.zbbquj.easypanel.host/login'
    html = f"""
    <div style="margin:0;padding:32px 16px;background:#f6f3ea;font-family:Arial,Helvetica,sans-serif;color:#1c1c17;">
        <div style="max-width:620px;margin:0 auto;background:#ffffff;border:1px solid #e7e2d7;border-radius:18px;overflow:hidden;box-shadow:0 12px 30px rgba(13,77,77,.08);">
            <div style="padding:28px 32px;background:#0d4d4d;color:#ffffff;">
                <div style="font-size:12px;font-weight:700;letter-spacing:3px;color:#f2c669;">ARKHÉ</div>
                <h1 style="margin:10px 0 0;font-size:25px;line-height:1.25;">Você recebeu um convite</h1>
            </div>

            <div style="padding:30px 32px;">
                <p style="margin:0 0 18px;font-size:15px;line-height:1.6;">Olá, <strong>{escape(str(nome or ''))}</strong>.</p>

                <p style="margin:0 0 18px;font-size:15px;line-height:1.6;">
                    A empresa <strong>{escape(str(empresa))}</strong> convidou você para acessar a conta empresarial dela no Banco Arkhé.
                </p>

                <div style="margin:22px 0;padding:16px 18px;background:#edf7f3;border-left:4px solid #d4af37;border-radius:10px;">
                    <div style="font-size:11px;font-weight:700;letter-spacing:1px;color:#736c5e;text-transform:uppercase;">Seu acesso</div>
                    <div style="margin-top:6px;font-size:16px;font-weight:700;color:#0d4d4d;">{escape(CARGOS.get(cargo, 'Outro'))}</div>
                </div>

                <h2 style="margin:26px 0 10px;font-size:18px;color:#0d4d4d;">Como aceitar</h2>
                <p style="margin:0 0 18px;font-size:15px;line-height:1.6;">
                    É bem simples: entre novamente no Arkhé com seu <strong>CPF e PIN pessoal</strong>.
                    Depois da validação facial, na tela <strong>“Escolha sua conta”</strong>, o convite aparecerá em
                    <strong>“Convites pendentes”</strong>. É só aceitar e entrar na empresa.
                </p>

                <div style="text-align:center;margin:28px 0;">
                    <a href="{url_login}" style="display:inline-block;padding:14px 26px;background:#0d4d4d;color:#ffffff;text-decoration:none;border-radius:10px;font-size:14px;font-weight:700;">
                        Acessar o Banco Arkhé
                    </a>
                </div>

                <p style="margin:0 0 8px;font-size:12px;line-height:1.6;color:#736c5e;">
                    Nenhum PIN ou senha da empresa foi compartilhado. O acesso usa sua própria identidade Arkhé.
                </p>
                <p style="margin:0;font-size:12px;line-height:1.6;color:#8a8374;">
                    Se o botão não abrir, acesse: <a href="{url_login}" style="color:#0d4d4d;">{url_login}</a>
                </p>
            </div>

            <div style="padding:18px 32px;background:#fbfaf6;border-top:1px solid #eee9df;font-size:11px;line-height:1.5;color:#8a8374;">
                Banco Arkhé · Ambiente educacional
            </div>
        </div>
    </div>
    """

    enviando_email(
        email,
        f'Você recebeu um convite no Arkhé - {empresa}',
        html
    )


def enviar_email_primeiro_acesso(email, nome, empresa, cargo, pin_temporario):
    url_login = 'https://arkhe-frontend.zbbquj.easypanel.host/login'
    html = f"""
    <div style="margin:0;padding:32px 16px;background:#f6f3ea;font-family:Arial,Helvetica,sans-serif;color:#1c1c17;">
        <div style="max-width:620px;margin:0 auto;background:#ffffff;border:1px solid #e7e2d7;border-radius:18px;overflow:hidden;box-shadow:0 12px 30px rgba(13,77,77,.08);">
            <div style="padding:28px 32px;background:#0d4d4d;color:#ffffff;">
                <div style="font-size:12px;font-weight:700;letter-spacing:3px;color:#f2c669;">ARKHÉ</div>
                <h1 style="margin:10px 0 0;font-size:25px;line-height:1.25;">Seu primeiro acesso está pronto</h1>
            </div>

            <div style="padding:30px 32px;">
                <p style="margin:0 0 18px;font-size:15px;line-height:1.6;">Olá, <strong>{escape(str(nome or ''))}</strong>.</p>

                <p style="margin:0 0 18px;font-size:15px;line-height:1.6;">
                    A empresa <strong>{escape(str(empresa))}</strong> convidou você para acessar a conta empresarial dela no Banco Arkhé.
                </p>

                <div style="margin:22px 0;padding:16px 18px;background:#edf7f3;border-left:4px solid #d4af37;border-radius:10px;">
                    <div style="font-size:11px;font-weight:700;letter-spacing:1px;color:#736c5e;text-transform:uppercase;">Seu acesso</div>
                    <div style="margin-top:6px;font-size:16px;font-weight:700;color:#0d4d4d;">{escape(CARGOS.get(cargo, 'Outro'))}</div>
                </div>

                <p style="margin:24px 0 8px;font-size:13px;font-weight:700;color:#736c5e;text-transform:uppercase;letter-spacing:1px;">PIN temporário</p>
                <div style="font-size:30px;font-weight:800;letter-spacing:7px;padding:18px;text-align:center;background:#fbfaf6;border:1px solid #e7e2d7;border-radius:12px;color:#0d4d4d;">
                    {escape(str(pin_temporario))}
                </div>
                <p style="margin:9px 0 22px;font-size:12px;line-height:1.6;color:#8a8374;">
                    Este PIN expira em 24 horas e será usado somente no seu primeiro acesso.
                </p>

                <h2 style="margin:26px 0 12px;font-size:18px;color:#0d4d4d;">O que fazer agora</h2>
                <ol style="margin:0 0 22px;padding-left:22px;font-size:15px;line-height:1.8;">
                    <li>Acesse o Arkhé pelo botão abaixo.</li>
                    <li>Entre com seu <strong>CPF</strong> e o <strong>PIN temporário</strong> acima.</li>
                    <li>Conclua a validação facial.</li>
                    <li>Crie seu <strong>PIN pessoal de 6 dígitos</strong>.</li>
                    <li>Na tela <strong>“Escolha sua conta”</strong>, aceite o convite em <strong>“Convites pendentes”</strong>.</li>
                    <li>Depois disso, a conta da empresa ficará disponível para você entrar normalmente.</li>
                </ol>

                <div style="text-align:center;margin:28px 0;">
                    <a href="{url_login}" style="display:inline-block;padding:14px 26px;background:#0d4d4d;color:#ffffff;text-decoration:none;border-radius:10px;font-size:14px;font-weight:700;">
                        Fazer meu primeiro acesso
                    </a>
                </div>

                <div style="margin-top:24px;padding:14px 16px;background:#fff8e8;border-radius:10px;font-size:12px;line-height:1.6;color:#6d5a29;">
                    Seu cadastro foi criado para permitir o acesso à empresa que enviou o convite.
                    Você não recebeu automaticamente uma conta bancária própria.
                </div>

                <p style="margin:18px 0 0;font-size:12px;line-height:1.6;color:#8a8374;">
                    Se o botão não abrir, acesse: <a href="{url_login}" style="color:#0d4d4d;">{url_login}</a>
                </p>
            </div>

            <div style="padding:18px 32px;background:#fbfaf6;border-top:1px solid #eee9df;font-size:11px;line-height:1.5;color:#8a8374;">
                Banco Arkhé · Ambiente educacional
            </div>
        </div>
    </div>
    """

    enviando_email(
        email,
        f'Seu acesso ao Arkhé - {empresa}',
        html
    )


@app.route('/acessos/verificar_usuario', methods=['POST'])
def verificar_usuario_acesso():
    contexto, erro = contexto_proprietario_pj()

    if erro:
        return erro

    dados = request.get_json() or {}
    cpf = dados.get('cpf')

    if not cpf:
        return jsonify({'mensagem': 'CPF não informado'}), 400

    cpf = ''.join(numero for numero in str(cpf) if numero.isdigit())

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT ID_USUARIO, NOME, EMAIL, TELEFONE
               FROM USUARIO
               WHERE CPF = ?""",
            (cpf,)
        )

        usuario = cursor.fetchone()

        if not usuario:
            return jsonify({
                'usuario_existente': False
            }), 200

        id_usuario = usuario[0]

        if id_usuario == contexto['id_usuario']:
            return jsonify({
                'usuario_existente': True,
                'proprietario': True,
                'mensagem': 'Este CPF pertence ao proprietário da conta'
            }), 200

        cursor.execute(
            """SELECT ID_ACESSO, CARGO, STATUS
               FROM ACESSO_CONTA
               WHERE ID_CONTA = ? AND ID_USUARIO = ?""",
            (
                contexto['id_conta'],
                id_usuario
            )
        )

        acesso = cursor.fetchone()

        resposta = {
            'usuario_existente': True,
            'proprietario': False,
            'usuario': {
                'id_usuario': id_usuario,
                'nome': usuario[1],
                'email': usuario[2],
                'telefone': usuario[3],
                'cpf': cpf
            },
            'possui_vinculo': acesso is not None
        }

        if acesso:
            resposta['acesso'] = {
                'id_acesso': acesso[0],
                'cargo': acesso[1],
                'cargo_nome': CARGOS.get(acesso[1], 'Outro'),
                'status': acesso[2],
                'status_nome': STATUS_ACESSO.get(acesso[2], 'Desconhecido')
            }

        return jsonify(resposta), 200

    except Exception as e:
        print('ERRO VERIFICAR USUARIO ACESSO:', e)

        return jsonify({
            'mensagem': 'Erro ao verificar usuário'
        }), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/acessos/convidar', methods=['POST'])
def convidar_acesso():
    contexto, erro = contexto_proprietario_pj()

    if erro:
        return erro

    dados = request.get_json() or {}

    cpf = dados.get('cpf')
    cargo = validar_cargo(dados.get('cargo'))

    if not cpf:
        return jsonify({'mensagem': 'CPF não informado'}), 400

    if cargo is None:
        return jsonify({'mensagem': 'Cargo inválido'}), 400

    cpf = ''.join(numero for numero in str(cpf) if numero.isdigit())

    nome = str(dados.get('nome') or '').strip()
    email = str(dados.get('email') or '').strip().lower()
    telefone = ''.join(
        numero
        for numero in str(dados.get('telefone') or '')
        if numero.isdigit()
    )

    cursor = None
    usuario_novo = False
    pin_temporario = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT ID_USUARIO, NOME, EMAIL, TELEFONE,
                      PRIMEIRO_ACESSO, PIN_TEMPORARIO_EXPIRA_EM
               FROM USUARIO
               WHERE CPF = ?""",
            (cpf,)
        )

        usuario = cursor.fetchone()

        if usuario:
            id_usuario_convidado = usuario[0]
            nome_usuario = usuario[1]
            email_usuario = usuario[2]
            telefone_usuario = usuario[3]

            if id_usuario_convidado == contexto['id_usuario']:
                return jsonify({
                    'mensagem': 'O proprietário da conta já possui acesso total à empresa'
                }), 400

        else:
            if not nome or not email or not telefone:
                return jsonify({
                    'mensagem': 'Nome, email e telefone são obrigatórios para uma pessoa que ainda não possui cadastro no Arkhé'
                }), 400

            cursor.execute(
                """SELECT 1
                   FROM USUARIO
                   WHERE EMAIL = ?""",
                (email,)
            )

            if cursor.fetchone():
                return jsonify({
                    'mensagem': 'Este email já pertence a outro usuário'
                }), 400

            pin_temporario = gerar_pin_temporario()
            pin_hash = criptografar_pin(pin_temporario)

            expiracao = data_atual() + datetime.timedelta(hours=24)

            cursor.execute(
                """INSERT INTO USUARIO
                   (NOME, EMAIL, TELEFONE, CPF, TIPO, STATUS, TENTATIVAS,
                    PIN_HASH, PRIMEIRO_ACESSO, PIN_TEMPORARIO_EXPIRA_EM)
                   VALUES (?, ?, ?, ?, 1, 1, 0, ?, 1, ?)
                   RETURNING ID_USUARIO""",
                (
                    nome,
                    email,
                    telefone,
                    cpf,
                    pin_hash,
                    expiracao
                )
            )

            id_usuario_convidado = cursor.fetchone()[0]

            nome_usuario = nome
            email_usuario = email
            telefone_usuario = telefone
            usuario_novo = True

        cursor.execute(
            """SELECT ID_ACESSO, CARGO, STATUS
               FROM ACESSO_CONTA
               WHERE ID_CONTA = ? AND ID_USUARIO = ?""",
            (
                contexto['id_conta'],
                id_usuario_convidado
            )
        )

        acesso_existente = cursor.fetchone()

        if acesso_existente:
            id_acesso = acesso_existente[0]
            status = acesso_existente[2]

            if status == 0:
                if usuario_novo:
                    con.rollback()

                return jsonify({
                    'mensagem': 'Este usuário já possui um convite pendente para esta empresa'
                }), 409

            if status == 1:
                if usuario_novo:
                    con.rollback()

                return jsonify({
                    'mensagem': 'Este usuário já possui acesso ativo a esta empresa'
                }), 409

            if status == 2:
                if usuario_novo:
                    con.rollback()

                return jsonify({
                    'mensagem': 'Este usuário possui um acesso bloqueado. Reative o acesso existente em vez de criar outro convite.'
                }), 409

            cursor.execute(
                """UPDATE ACESSO_CONTA
                   SET CARGO = ?,
                       STATUS = 0,
                       ID_CONCEDIDO_POR = ?,
                       DATA_CONVITE = CURRENT_TIMESTAMP,
                       DATA_ATIVACAO = NULL
                   WHERE ID_ACESSO = ?""",
                (
                    cargo,
                    contexto['id_usuario'],
                    id_acesso
                )
            )

        else:
            cursor.execute(
                """INSERT INTO ACESSO_CONTA
                   (ID_CONTA, ID_USUARIO, CARGO, STATUS, ID_CONCEDIDO_POR)
                   VALUES (?, ?, ?, 0, ?)
                   RETURNING ID_ACESSO""",
                (
                    contexto['id_conta'],
                    id_usuario_convidado,
                    cargo,
                    contexto['id_usuario']
                )
            )

            id_acesso = cursor.fetchone()[0]

        con.commit()

        empresa = nome_empresa(contexto)

        if usuario_novo:
            enviar_email_primeiro_acesso(
                email_usuario,
                nome_usuario,
                empresa,
                cargo,
                pin_temporario
            )

        else:
            enviar_email_convite_existente(
                email_usuario,
                nome_usuario,
                empresa,
                cargo
            )

        return jsonify({
            'mensagem': (
                'Usuário criado e convite enviado com sucesso'
                if usuario_novo
                else 'Convite enviado com sucesso'
            ),
            'id_acesso': id_acesso,
            'id_usuario': id_usuario_convidado,
            'usuario_novo': usuario_novo,
            'conta_criada': False,
            'status': 0,
            'status_nome': 'Pendente',
            'cargo': cargo,
            'cargo_nome': CARGOS[cargo]
        }), 201

    except Exception as e:
        con.rollback()

        print('ERRO CONVIDAR ACESSO:', e)

        return jsonify({
            'mensagem': 'Erro ao criar convite'
        }), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/acessos', methods=['GET'])
def listar_acessos():
    contexto, erro = contexto_proprietario_pj()

    if erro:
        return erro

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT A.ID_ACESSO, A.ID_USUARIO, U.NOME, U.EMAIL,
                      U.TELEFONE, U.CPF, A.CARGO, A.STATUS,
                      A.DATA_CONVITE, A.DATA_ATIVACAO
               FROM ACESSO_CONTA A
               INNER JOIN USUARIO U ON U.ID_USUARIO = A.ID_USUARIO
               WHERE A.ID_CONTA = ?
               ORDER BY A.STATUS, U.NOME""",
            (contexto['id_conta'],)
        )

        acessos_banco = cursor.fetchall()
        acessos = []

        for acesso in acessos_banco:
            acessos.append({
                'id_acesso': acesso[0],
                'id_usuario': acesso[1],
                'nome': acesso[2],
                'email': acesso[3],
                'telefone': acesso[4],
                'cpf': acesso[5],
                'cargo': acesso[6],
                'cargo_nome': CARGOS.get(acesso[6], 'Outro'),
                'status': acesso[7],
                'status_nome': STATUS_ACESSO.get(
                    acesso[7],
                    'Desconhecido'
                ),
                'data_convite': (
                    str(acesso[8])
                    if acesso[8]
                    else None
                ),
                'data_ativacao': (
                    str(acesso[9])
                    if acesso[9]
                    else None
                )
            })

        return jsonify({
            'empresa': {
                'id_conta': contexto['id_conta'],
                'cnpj': contexto['cnpj'],
                'nome_fantasia': contexto['nome_fantasia'],
                'razao_social': contexto['razao_social']
            },
            'acessos': acessos
        }), 200

    except Exception as e:
        print('ERRO LISTAR ACESSOS:', e)

        return jsonify({
            'mensagem': 'Erro ao listar acessos'
        }), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/convites_pendentes', methods=['GET'])
def convites_pendentes():
    id_usuario = descobre_id_usuario()

    if not id_usuario:
        return jsonify({
            'mensagem': 'Usuário não autenticado'
        }), 401

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT A.ID_ACESSO, A.ID_CONTA, A.CARGO,
                      A.DATA_CONVITE,
                      C.CNPJ, C.NOME_FANTASIA, C.RAZAO_SOCIAL,
                      U.NOME
               FROM ACESSO_CONTA A
               INNER JOIN CONTA C ON C.ID_CONTA = A.ID_CONTA
               INNER JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
               WHERE A.ID_USUARIO = ?
                 AND A.STATUS = 0
                 AND C.TIPO_CONTA = 1
               ORDER BY A.DATA_CONVITE DESC""",
            (id_usuario,)
        )

        convites_banco = cursor.fetchall()
        convites = []

        for convite in convites_banco:
            empresa = (
                convite[5]
                or convite[6]
                or convite[7]
                or 'Empresa Arkhé'
            )

            convites.append({
                'id_acesso': convite[0],
                'id_conta': convite[1],
                'cargo': convite[2],
                'cargo_nome': CARGOS.get(
                    convite[2],
                    'Outro'
                ),
                'data_convite': (
                    str(convite[3])
                    if convite[3]
                    else None
                ),
                'cnpj': convite[4],
                'nome_fantasia': convite[5],
                'razao_social': convite[6],
                'empresa': empresa
            })

        return jsonify({
            'convites': convites
        }), 200

    except Exception as e:
        print('ERRO LISTAR CONVITES:', e)

        return jsonify({
            'mensagem': 'Erro ao listar convites'
        }), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/convites/<int:id_acesso>/aceitar', methods=['POST'])
def aceitar_convite(id_acesso):
    id_usuario = descobre_id_usuario()

    if not id_usuario:
        return jsonify({
            'mensagem': 'Usuário não autenticado'
        }), 401

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT PIN_HASH, PRIMEIRO_ACESSO
               FROM USUARIO
               WHERE ID_USUARIO = ?""",
            (id_usuario,)
        )

        usuario = cursor.fetchone()

        if not usuario:
            return jsonify({
                'mensagem': 'Usuário não encontrado'
            }), 404

        if usuario[0] is None or usuario[1] == 1:
            return jsonify({
                'mensagem': 'Defina seu PIN pessoal antes de aceitar o convite',
                'troca_pin_obrigatoria': True
            }), 403

        cursor.execute(
            """SELECT A.ID_ACESSO
               FROM ACESSO_CONTA A
               INNER JOIN CONTA C ON C.ID_CONTA = A.ID_CONTA
               WHERE A.ID_ACESSO = ?
                 AND A.ID_USUARIO = ?
                 AND A.STATUS = 0
                 AND C.TIPO_CONTA = 1""",
            (
                id_acesso,
                id_usuario
            )
        )

        convite = cursor.fetchone()

        if not convite:
            return jsonify({
                'mensagem': 'Convite pendente não encontrado'
            }), 404

        cursor.execute(
            """UPDATE ACESSO_CONTA
               SET STATUS = 1,
                   DATA_ATIVACAO = CURRENT_TIMESTAMP
               WHERE ID_ACESSO = ?
                 AND ID_USUARIO = ?
                 AND STATUS = 0""",
            (
                id_acesso,
                id_usuario
            )
        )

        con.commit()

        return jsonify({
            'mensagem': 'Convite aceito com sucesso',
            'id_acesso': id_acesso,
            'status': 1,
            'status_nome': 'Ativo'
        }), 200

    except Exception as e:
        con.rollback()

        print('ERRO ACEITAR CONVITE:', e)

        return jsonify({
            'mensagem': 'Erro ao aceitar convite'
        }), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/convites/<int:id_acesso>/recusar', methods=['POST'])
def recusar_convite(id_acesso):
    id_usuario = descobre_id_usuario()

    if not id_usuario:
        return jsonify({
            'mensagem': 'Usuário não autenticado'
        }), 401

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT ID_ACESSO
               FROM ACESSO_CONTA
               WHERE ID_ACESSO = ?
                 AND ID_USUARIO = ?
                 AND STATUS = 0""",
            (
                id_acesso,
                id_usuario
            )
        )

        convite = cursor.fetchone()

        if not convite:
            return jsonify({
                'mensagem': 'Convite pendente não encontrado'
            }), 404

        cursor.execute(
            """UPDATE ACESSO_CONTA
               SET STATUS = 3,
                   DATA_ATIVACAO = NULL
               WHERE ID_ACESSO = ?
                 AND ID_USUARIO = ?""",
            (
                id_acesso,
                id_usuario
            )
        )

        con.commit()

        return jsonify({
            'mensagem': 'Convite recusado',
            'id_acesso': id_acesso,
            'status': 3,
            'status_nome': 'Revogado'
        }), 200

    except Exception as e:
        con.rollback()

        print('ERRO RECUSAR CONVITE:', e)

        return jsonify({
            'mensagem': 'Erro ao recusar convite'
        }), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/acessos/<int:id_acesso>/cargo', methods=['PUT'])
def alterar_cargo_acesso(id_acesso):
    contexto, erro = contexto_proprietario_pj()

    if erro:
        return erro

    dados = request.get_json() or {}
    cargo = validar_cargo(dados.get('cargo'))

    if cargo is None:
        return jsonify({
            'mensagem': 'Cargo inválido'
        }), 400

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT ID_ACESSO, STATUS
               FROM ACESSO_CONTA
               WHERE ID_ACESSO = ?
                 AND ID_CONTA = ?""",
            (
                id_acesso,
                contexto['id_conta']
            )
        )

        acesso = cursor.fetchone()

        if not acesso:
            return jsonify({
                'mensagem': 'Acesso não encontrado'
            }), 404

        if acesso[1] == 3:
            return jsonify({
                'mensagem': 'Não é possível alterar o cargo de um acesso revogado'
            }), 400

        cursor.execute(
            """UPDATE ACESSO_CONTA
               SET CARGO = ?
               WHERE ID_ACESSO = ?
                 AND ID_CONTA = ?""",
            (
                cargo,
                id_acesso,
                contexto['id_conta']
            )
        )

        con.commit()

        return jsonify({
            'mensagem': 'Cargo atualizado com sucesso',
            'id_acesso': id_acesso,
            'cargo': cargo,
            'cargo_nome': CARGOS[cargo]
        }), 200

    except Exception as e:
        con.rollback()

        print('ERRO ALTERAR CARGO:', e)

        return jsonify({
            'mensagem': 'Erro ao alterar cargo'
        }), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/acessos/<int:id_acesso>/bloquear', methods=['PUT'])
def bloquear_acesso(id_acesso):
    contexto, erro = contexto_proprietario_pj()

    if erro:
        return erro

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT STATUS
               FROM ACESSO_CONTA
               WHERE ID_ACESSO = ?
                 AND ID_CONTA = ?""",
            (
                id_acesso,
                contexto['id_conta']
            )
        )

        acesso = cursor.fetchone()

        if not acesso:
            return jsonify({
                'mensagem': 'Acesso não encontrado'
            }), 404

        if acesso[0] != 1:
            return jsonify({
                'mensagem': 'Somente acessos ativos podem ser bloqueados'
            }), 400

        cursor.execute(
            """UPDATE ACESSO_CONTA
               SET STATUS = 2
               WHERE ID_ACESSO = ?
                 AND ID_CONTA = ?""",
            (
                id_acesso,
                contexto['id_conta']
            )
        )

        con.commit()

        return jsonify({
            'mensagem': 'Acesso bloqueado com sucesso',
            'status': 2,
            'status_nome': 'Bloqueado'
        }), 200

    except Exception as e:
        con.rollback()

        print('ERRO BLOQUEAR ACESSO:', e)

        return jsonify({
            'mensagem': 'Erro ao bloquear acesso'
        }), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/acessos/<int:id_acesso>/ativar', methods=['PUT'])
def ativar_acesso(id_acesso):
    contexto, erro = contexto_proprietario_pj()

    if erro:
        return erro

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT STATUS
               FROM ACESSO_CONTA
               WHERE ID_ACESSO = ?
                 AND ID_CONTA = ?""",
            (
                id_acesso,
                contexto['id_conta']
            )
        )

        acesso = cursor.fetchone()

        if not acesso:
            return jsonify({
                'mensagem': 'Acesso não encontrado'
            }), 404

        if acesso[0] != 2:
            return jsonify({
                'mensagem': 'Somente acessos bloqueados podem ser reativados'
            }), 400

        cursor.execute(
            """UPDATE ACESSO_CONTA
               SET STATUS = 1
               WHERE ID_ACESSO = ?
                 AND ID_CONTA = ?""",
            (
                id_acesso,
                contexto['id_conta']
            )
        )

        con.commit()

        return jsonify({
            'mensagem': 'Acesso reativado com sucesso',
            'status': 1,
            'status_nome': 'Ativo'
        }), 200

    except Exception as e:
        con.rollback()

        print('ERRO ATIVAR ACESSO:', e)

        return jsonify({
            'mensagem': 'Erro ao reativar acesso'
        }), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/acessos/<int:id_acesso>', methods=['DELETE'])
def revogar_acesso(id_acesso):
    contexto, erro = contexto_proprietario_pj()

    if erro:
        return erro

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT STATUS
               FROM ACESSO_CONTA
               WHERE ID_ACESSO = ?
                 AND ID_CONTA = ?""",
            (
                id_acesso,
                contexto['id_conta']
            )
        )

        acesso = cursor.fetchone()

        if not acesso:
            return jsonify({
                'mensagem': 'Acesso não encontrado'
            }), 404

        if acesso[0] == 3:
            return jsonify({
                'mensagem': 'Este acesso já está revogado'
            }), 400

        cursor.execute(
            """UPDATE ACESSO_CONTA
               SET STATUS = 3,
                   DATA_ATIVACAO = NULL
               WHERE ID_ACESSO = ?
                 AND ID_CONTA = ?""",
            (
                id_acesso,
                contexto['id_conta']
            )
        )

        con.commit()

        return jsonify({
            'mensagem': 'Acesso revogado com sucesso',
            'status': 3,
            'status_nome': 'Revogado'
        }), 200

    except Exception as e:
        con.rollback()

        print('ERRO REVOGAR ACESSO:', e)

        return jsonify({
            'mensagem': 'Erro ao revogar acesso'
        }), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/acessos/<int:id_acesso>/reenviar-convite', methods=['POST'])
def reenviar_convite(id_acesso):
    contexto, erro = contexto_proprietario_pj()

    if erro:
        return erro

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT A.ID_USUARIO, A.CARGO, A.STATUS,
                      U.NOME, U.EMAIL, U.PRIMEIRO_ACESSO,
                      U.PIN_TEMPORARIO_EXPIRA_EM
               FROM ACESSO_CONTA A
               INNER JOIN USUARIO U ON U.ID_USUARIO = A.ID_USUARIO
               WHERE A.ID_ACESSO = ?
                 AND A.ID_CONTA = ?""",
            (
                id_acesso,
                contexto['id_conta']
            )
        )

        acesso = cursor.fetchone()

        if not acesso:
            return jsonify({
                'mensagem': 'Convite não encontrado'
            }), 404

        if acesso[2] != 0:
            return jsonify({
                'mensagem': 'Somente convites pendentes podem ser reenviados'
            }), 400

        id_usuario_convidado = acesso[0]
        cargo = acesso[1]
        nome_usuario = acesso[3]
        email_usuario = acesso[4]
        primeiro_acesso = acesso[5]
        expiracao_temporaria = acesso[6]

        empresa = nome_empresa(contexto)

        novo_pin_temporario = None

        if primeiro_acesso == 1 and expiracao_temporaria is not None:
            novo_pin_temporario = gerar_pin_temporario()
            novo_hash = criptografar_pin(novo_pin_temporario)

            nova_expiracao = (
                data_atual()
                + datetime.timedelta(hours=24)
            )

            cursor.execute(
                """UPDATE USUARIO
                   SET PIN_HASH = ?,
                       PIN_TEMPORARIO_EXPIRA_EM = ?
                   WHERE ID_USUARIO = ?""",
                (
                    novo_hash,
                    nova_expiracao,
                    id_usuario_convidado
                )
            )

            con.commit()

            enviar_email_primeiro_acesso(
                email_usuario,
                nome_usuario,
                empresa,
                cargo,
                novo_pin_temporario
            )

        else:
            enviar_email_convite_existente(
                email_usuario,
                nome_usuario,
                empresa,
                cargo
            )

        return jsonify({
            'mensagem': 'Convite reenviado com sucesso',
            'pin_temporario_renovado': novo_pin_temporario is not None
        }), 200

    except Exception as e:
        con.rollback()

        print('ERRO REENVIAR CONVITE:', e)

        return jsonify({
            'mensagem': 'Erro ao reenviar convite'
        }), 500

    finally:
        if cursor:
            cursor.close()