"""WhatsApp account linking, activation, identity, and permission routes."""
import hashlib
import json
import os
import re
import secrets
from urllib.parse import quote

import redis
import requests
from flask import jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from banco import con
from funcao import descobre_id_conta, descobre_id_usuario, usuario_pode_acessar_conta
from main import app


def _conta_configuravel():
    usuario, conta = descobre_id_usuario(), descobre_id_conta()
    if not usuario or not conta or not usuario_pode_acessar_conta(usuario, conta):
        return None, (jsonify({"mensagem": "Autenticacao necessaria"}), 401)
    cursor = con.cursor()
    try:
        cursor.execute("SELECT ID_USUARIO, WHATSAPP_AUTORIZADO, WHATSAPP_NIVEL FROM CONTA WHERE ID_CONTA = ?", (conta,))
        registro = cursor.fetchone()
    finally:
        cursor.close()
    if not registro:
        return None, (jsonify({"mensagem": "Conta nao encontrada"}), 404)
    # Configuracao de canal e gerenciada exclusivamente pelo titular.
    if int(registro[0]) != int(usuario):
        return None, (jsonify({"mensagem": "Somente o titular pode configurar o canal WhatsApp"}), 403)
    return {"id_conta": conta, "autorizado": int(registro[1]), "nivel": int(registro[2]), "tipo_conta": int(_tipo_conta(conta))}, None


def _tipo_conta(id_conta):
    cursor = con.cursor()
    try:
        cursor.execute("SELECT TIPO_CONTA FROM CONTA WHERE ID_CONTA = ?", (id_conta,))
        linha = cursor.fetchone()
        return int(linha[0]) if linha else 0
    finally:
        cursor.close()


@app.route("/whatsapp/configuracao", methods=["GET"])
def whatsapp_configuracao_get():
    conta, erro = _conta_configuravel()
    return erro if erro else jsonify(conta)


@app.route("/whatsapp/configuracao", methods=["PUT"])
def whatsapp_configuracao_put():
    conta, erro = _conta_configuravel()
    if erro:
        return erro
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict) or type(dados.get("autorizado")) is not bool or type(dados.get("nivel")) is not int:
        return jsonify({"mensagem": "Informe autorizado (booleano) e nivel (1, 2 ou 3)"}), 400
    nivel = dados["nivel"]
    if nivel not in ((1, 2) if conta["tipo_conta"] == 0 else (1, 2, 3)):
        return jsonify({"mensagem": "Nivel invalido"}), 400
    autorizado = int(dados["autorizado"])
    cursor = con.cursor()
    try:
        cursor.execute("UPDATE CONTA SET WHATSAPP_AUTORIZADO = ?, WHATSAPP_NIVEL = ? WHERE ID_CONTA = ?", (autorizado, nivel, conta["id_conta"]))
        con.commit()
    except Exception:
        con.rollback()
        app.logger.exception("Falha ao atualizar configuracao WhatsApp")
        return jsonify({"mensagem": "Nao foi possivel atualizar a configuracao"}), 500
    finally:
        cursor.close()
    return jsonify({"id_conta": conta["id_conta"], "autorizado": autorizado, "nivel": nivel, "tipo_conta": conta["tipo_conta"]})


def _servico_valido():
    segredo = os.getenv("N8N_SERVICE_KEY")
    recebido = request.headers.get("X-Arkhe-N8N-Key")
    return bool(segredo and recebido and secrets.compare_digest(segredo, recebido))


# Lista as contas ativadas e permitidas para o remetente autenticado pelo n8n.
@app.route("/internal/whatsapp/contexto", methods=["POST"])
def whatsapp_contexto():
    if not _servico_valido():
        return jsonify({"mensagem": "Servico nao autorizado"}), 401
    # O identificador vem exclusivamente do n8n autenticado.
    # A identidade e as contas sao validadas de novo no Firebird.
    dados = request.get_json(silent=True) or {}
    chat_id = str(dados.get("chatId", ""))
    try:
        identidade, contas = _listar_contas_autorizadas(chat_id)
    except Exception:
        app.logger.exception("Falha ao consultar contexto WhatsApp")
        return jsonify({"mensagem": "Contexto indisponivel"}), 503
    if not identidade or not contas:
        return jsonify({"vinculado": False, "contas": [], "mensagem": "Ative seu WhatsApp pelo site Arkhé"})
    ativa = next((c for c in contas if c["id_conta"] == identidade["id_conta"]), None)
    return jsonify({"vinculado": True, "id_usuario": identidade["id_usuario"],
                    "conta_selecionada": ativa["id_conta"] if ativa else None,
                    "nivel": ativa["nivel"] if ativa else None,
                    "selecao_necessaria": ativa is None, "contas": contas})


@app.route("/internal/whatsapp/iniciar", methods=["POST"])
def whatsapp_legado_iniciar():
    return jsonify({"mensagem": "Rota legada desativada ate vinculacao segura"}), 403


# Seleciona uma conta previamente ativada pelo titular; nao cria autorizacoes.
@app.route("/internal/whatsapp/selecionar-conta", methods=["POST"])
def whatsapp_selecionar_conta():
    if not _servico_valido():
        return jsonify({"mensagem": "Servico nao autorizado"}), 401
    dados = request.get_json(silent=True) or {}
    chat_id, id_conta = str(dados.get("chatId", "")), dados.get("id_conta")
    if type(id_conta) is not int or id_conta <= 0:
        return jsonify({"mensagem": "Informe um id_conta valido"}), 400
    try:
        identidade, contas = _listar_contas_autorizadas(chat_id)
        escolhida = next((c for c in contas if c["id_conta"] == id_conta), None)
        if not identidade or not escolhida:
            return jsonify({"mensagem": "Conta nao vinculada ou nao autorizada"}), 403
        chave, redis_cli = _chave_remetente(chat_id), _redis_wa()
        # WATCH evita sobrescrever uma ativacao simultanea de outra conta.
        with redis_cli.pipeline() as pipe:
            for tentativa in range(3):
                try:
                    pipe.watch(chave)
                    texto = pipe.get(chave)
                    atual = json.loads(texto) if texto else {}
                    if (atual.get("chat_id") != chat_id or
                            int(atual.get("id_usuario", -1)) != identidade["id_usuario"] or
                            id_conta not in _ids_vinculados(atual)):
                        return jsonify({"mensagem": "Vinculo alterado. Consulte as contas novamente"}), 409
                    prazo = pipe.ttl(chave)
                    if prazo <= 0:
                        return jsonify({"mensagem": "Vinculo expirado. Ative novamente"}), 403
                    atual["id_conta"] = id_conta
                    pipe.multi()
                    pipe.set(chave, json.dumps(atual), ex=prazo)
                    pipe.execute()
                    break
                except redis.WatchError:
                    continue
            else:
                return jsonify({"mensagem": "Operacao concorrente. Tente novamente"}), 409
        return jsonify({"selecionada": True, "id_conta": id_conta, "nivel": escolhida["nivel"]})
    except Exception:
        app.logger.exception("Falha ao selecionar conta WhatsApp")
        return jsonify({"mensagem": "Nao foi possivel selecionar a conta"}), 503


def _normalizar_telefone(valor):
    digitos = re.sub(r"\D", "", str(valor or ""))
    if digitos.startswith("55") and len(digitos) in (12, 13):
        digitos = digitos[2:]
    return digitos if len(digitos) in (10, 11) else None


@app.route("/whatsapp/link", methods=["POST"])
def whatsapp_criar_link():
    """Cria um convite temporario; nao concede acesso financeiro por si so."""
    conta, erro = _conta_configuravel()
    if erro:
        return erro
    if not conta["autorizado"]:
        return jsonify({"mensagem": "Autorize o WhatsApp antes de iniciar a vinculacao"}), 403
    destino = re.sub(r"\D", "", os.getenv("ARKHE_WHATSAPP_NUMBER", ""))
    if len(destino) not in (12, 13) or not destino.startswith("55"):
        return jsonify({"mensagem": "Numero oficial do WhatsApp ainda nao configurado no servidor"}), 503
    usuario = descobre_id_usuario()
    cursor = con.cursor()
    try:
        cursor.execute("SELECT TELEFONE FROM USUARIO WHERE ID_USUARIO = ?", (usuario,))
        registro = cursor.fetchone()
    finally:
        cursor.close()
    numero = _normalizar_telefone(registro[0] if registro else None)
    if not numero:
        return jsonify({"mensagem": "Cadastre um telefone valido no seu perfil antes de vincular"}), 422
    codigo = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="arkhe-wa-v1").dumps(
        {"usuario": usuario, "conta": conta["id_conta"], "telefone": numero})
    texto = "Ola Arkhe! Quero iniciar a vinculacao do meu WhatsApp. Codigo: " + codigo
    return jsonify({"url": "https://wa.me/" + destino + "?text=" + quote(texto),
                    "expira_em_segundos": 600, "mensagem": "Envie a mensagem pronta pelo WhatsApp"})


@app.route("/internal/whatsapp/validar-convite", methods=["POST"])
def whatsapp_validar_convite():
    """Valida convite e remetente para saudacao. NAO emite token bancario."""
    if not _servico_valido():
        return jsonify({"mensagem": "Servico nao autorizado"}), 401
    dados = request.get_json(silent=True) or {}
    remetente = str(dados.get("chatId", ""))
    if not ((remetente.endswith("@c.us") or remetente.endswith("@lid")) and remetente.split("@")[0].isdigit()):
        return jsonify({"vinculado": False, "mensagem": "Nao foi possivel validar automaticamente o identificador do WhatsApp"}), 403
    numero = _normalizar_telefone(remetente.split("@")[0])
    try:
        token = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="arkhe-wa-v1").loads(
            str(dados.get("codigo", "")), max_age=600)
    except (BadSignature, SignatureExpired):
        return jsonify({"vinculado": False, "mensagem": "Convite invalido ou expirado. Gere outro pelo site"}), 403
    # LID nao representa diretamente o telefone: resolvemos via WAHA confiavel.
    try:
        numero = _resolver_lid_pelo_waha(remetente)
    except Exception:
        numero = None
    if not numero or numero != token.get("telefone"):
        return jsonify({"vinculado": False, "mensagem": "Use o mesmo numero cadastrado no Arkhé"}), 403
    cursor = con.cursor()
    try:
        cursor.execute("""SELECT C.WHATSAPP_AUTORIZADO, C.WHATSAPP_NIVEL
                          FROM CONTA C JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
                          WHERE C.ID_CONTA = ? AND C.ID_USUARIO = ? AND U.TELEFONE IS NOT NULL""",
                       (token.get("conta"), token.get("usuario")))
        registro = cursor.fetchone()
        cursor.execute("SELECT TELEFONE FROM USUARIO WHERE ID_USUARIO = ?", (token.get("usuario"),))
        telefone = cursor.fetchone()
    finally:
        cursor.close()
    if not registro or not registro[0] or not telefone or _normalizar_telefone(telefone[0]) != numero:
        return jsonify({"vinculado": False, "mensagem": "Autorizacao desativada ou telefone alterado"}), 403
    return _salvar_vinculo_whatsapp(remetente, token, registro)


# Redis de autorizacao, separado da memoria conversacional do agente.
# Nunca utilizar texto do Gemini ou historico como prova de autenticacao.
def _redis_wa():
    endereco = os.getenv("ARKHE_WHATSAPP_REDIS_URL") or os.getenv("REDIS_URL")
    if not endereco:
        raise RuntimeError("ARKHE_WHATSAPP_REDIS_URL nao configurada")
    return redis.Redis.from_url(endereco, decode_responses=True, socket_connect_timeout=3, socket_timeout=3)


def _chave_remetente(chat_id):
    return "arkhe:wa:binding:v1:" + hashlib.sha256(chat_id.encode("utf-8")).hexdigest()


def _ids_vinculados(identidade):
    """Le vínculos antigos (uma conta) e novos (varias contas)."""
    try:
        ids = identidade.get("contas_vinculadas") or [identidade["id_conta"]]
        return sorted({int(valor) for valor in ids if int(valor) > 0})
    except (KeyError, TypeError, ValueError):
        return []


def _ler_vinculo(chat_id):
    """Identifica a pessoa somente por um JID previamente vinculado no Redis."""
    if not _jid_valido(chat_id):
        return None
    valor = _redis_wa().get(_chave_remetente(chat_id))
    if not valor:
        return None
    try:
        identidade = json.loads(valor)
        if (not isinstance(identidade, dict) or identidade.get("chat_id") != chat_id or
                not _ids_vinculados(identidade)):
            return None
        identidade["id_usuario"] = int(identidade["id_usuario"])
        identidade["id_conta"] = int(identidade["id_conta"])
        return identidade
    except (KeyError, ValueError, TypeError):
        return None


def _guardar_vinculo(chat_id, id_usuario, id_conta, telefone, redis_cli=None):
    """Acrescenta uma conta confirmada sem apagar as outras contas do usuario."""
    redis_cli = redis_cli or _redis_wa()
    chave = _chave_remetente(chat_id)
    with redis_cli.pipeline() as pipe:
        for tentativa in range(3):
            try:
                pipe.watch(chave)
                texto = pipe.get(chave)
                anterior = json.loads(texto) if texto else None
                if anterior:
                    # Um WhatsApp já associado a outra identidade nao pode ser assumido
                    # por um novo usuario apenas ativando uma conta diferente.
                    if (anterior.get("chat_id") != chat_id or
                            int(anterior.get("id_usuario", -1)) != int(id_usuario) or
                            anterior.get("telefone") != telefone):
                        raise ValueError("WhatsApp associado a outra identidade")
                contas = _ids_vinculados(anterior) if anterior else []
                contas = sorted(set(contas + [int(id_conta)]))
                vinculo = {"id_usuario": int(id_usuario), "id_conta": int(id_conta),
                           "contas_vinculadas": contas, "telefone": telefone, "chat_id": chat_id}
                pipe.multi()
                pipe.set(chave, json.dumps(vinculo), ex=VINCULO_TTL)
                pipe.execute()
                return vinculo
            except redis.WatchError:
                continue
    raise RuntimeError("Concorrencia ao salvar vinculo WhatsApp")


def _listar_contas_autorizadas(chat_id):
    """Confere no Firebird quais contas ativadas continuam liberadas para este usuario."""
    identidade = _ler_vinculo(chat_id)
    if not identidade:
        return None, []
    ids = _ids_vinculados(identidade)
    placeholders = ", ".join("?" for _ in ids)
    cursor = con.cursor()
    try:
        cursor.execute(
            """SELECT C.ID_CONTA, C.WHATSAPP_AUTORIZADO, C.WHATSAPP_NIVEL,
                      C.TIPO_CONTA, U.TELEFONE, C.NOME_FANTASIA,
                      C.RAZAO_SOCIAL, C.NUMERO_CONTA
               FROM CONTA C JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
               WHERE C.ID_USUARIO = ? AND C.ID_CONTA IN (""" + placeholders + ")",
            (identidade["id_usuario"], *ids))
        registros = cursor.fetchall()
    finally:
        cursor.close()
    contas = []
    for conta in registros:
        if (_normalizar_telefone(conta[4]) != identidade["telefone"] or
                int(conta[1] or 0) != 1):
            continue
        tipo, nivel = int(conta[3]), int(conta[2] or 0)
        if tipo == 0:
            nivel = min(nivel, 2)
        if nivel >= 1:
            # Um apelido ajuda o MAURO a diferenciar contas sem expor CPF ou CNPJ.
            descricao = "Conta pessoal" if tipo == 0 else str(conta[5] or conta[6] or "Conta empresarial")
            contas.append({"id_conta": int(conta[0]), "tipo_conta": tipo, "nivel": nivel,
                           "descricao": descricao, "conta_final": str(conta[7] or "")[-4:]})
    contas.sort(key=lambda item: item["id_conta"])
    return identidade, contas


def _conta_vinculada(chat_id):
    """Devolve somente a conta ativa e ainda autorizada; nunca escolhe outra sozinho."""
    identidade, contas = _listar_contas_autorizadas(chat_id)
    if not identidade:
        return None
    ativa = next((c for c in contas if c["id_conta"] == identidade["id_conta"]), None)
    return {**identidade, "nivel": ativa["nivel"]} if ativa else None


def verificar_nivel_whatsapp(chat_id, nivel_necessario=1):
    """Valida vínculo, conta selecionada e nível atual antes da operacao bancaria."""
    conta = _conta_vinculada(chat_id)
    if not conta:
        return None, "WhatsApp sem conta selecionada ou autorizada"
    if conta["nivel"] < nivel_necessario:
        return None, "Nivel de WhatsApp insuficiente para esta operacao"
    return conta, None


def _salvar_vinculo_whatsapp(remetente, token, registro):
    """Confirma o convite legado e acrescenta a conta sem substituir as anteriores."""
    try:
        redis_cli = _redis_wa()
        codigo_hash = hashlib.sha256(str(request.get_json(silent=True).get("codigo", "")).encode("utf-8")).hexdigest()
        if not redis_cli.set("arkhe:wa:convite-usado:" + codigo_hash, "1", nx=True, ex=600):
            return jsonify({"vinculado": False, "mensagem": "Convite ja utilizado. Gere outro no site"}), 409
        _guardar_vinculo(remetente, token["usuario"], token["conta"], token["telefone"], redis_cli)
    except ValueError:
        return jsonify({"vinculado": False, "mensagem": "Este WhatsApp ja pertence a outro usuario. Revogue o vinculo anterior"}), 403
    except Exception:
        app.logger.exception("Falha Redis vinculo WhatsApp")
        return jsonify({"vinculado": False, "mensagem": "Nao foi possivel vincular o WhatsApp. Verifique Redis"}), 503
    return jsonify({"convite_validado": True, "vinculado": True, "nivel": int(registro[1]),
                    "mensagem": "WhatsApp vinculado com a conta Arkhé."})

PENDENCIA_TTL = 600


VINCULO_TTL = 30 * 24 * 60 * 60


def _chave_pendente(telefone):
    return "arkhe:wa:pendente:v2:" + hashlib.sha256(telefone.encode()).hexdigest()


def _chave_pendente_chat(chat_id):
    return "arkhe:wa:pendente-chat:v2:" + hashlib.sha256(chat_id.encode()).hexdigest()


def _telefone_do_jid(jid):
    if not isinstance(jid, str) or not re.fullmatch(r"55[0-9]{10,11}@c\.us", jid):
        return None
    return _normalizar_telefone(jid.split("@", 1)[0])


def _jid_valido(chat_id):
    return isinstance(chat_id, str) and bool(re.fullmatch(r"[0-9]{6,20}@(c\.us|lid)", chat_id))


def _credenciais_waha():
    url = os.getenv("WAHA_API_URL", "").rstrip("/")
    chave = os.getenv("WAHA_API_KEY", "")
    if not url.startswith("https://") or not chave:
        raise RuntimeError("WAHA_API_URL ou WAHA_API_KEY não configurada")
    return url, {"X-Api-Key": chave}


def _resolver_lid_pelo_waha(chat_id):
    """Só confia no número devolvido pela sessão WAHA, nunca em texto do usuário."""
    if chat_id.endswith("@c.us"):
        return _telefone_do_jid(chat_id)
    if not chat_id.endswith("@lid"):
        return None
    url, headers = _credenciais_waha()
    resposta = requests.get(url + "/api/arkhe/lids/" + quote(chat_id, safe=""),
                            headers=headers, timeout=8)
    if resposta.status_code != 200:
        app.logger.warning("WAHA não resolveu LID: HTTP %s", resposta.status_code)
        return None
    dados = resposta.json()
    return _telefone_do_jid(dados.get("pn")) if isinstance(dados, dict) else None


def _descobrir_chat_destino(telefone):
    """Consulta o WAHA para descobrir o JID real do telefone (incluindo @lid)."""
    url, headers = _credenciais_waha()
    try:
        resposta = requests.get(url + "/api/contacts/check-exists",
            params={"phone": "55" + telefone, "session": "arkhe"}, headers=headers, timeout=8)
        if resposta.ok:
            dados = resposta.json()
            encontrado = dados.get("chatId") if isinstance(dados, dict) else None
            if dados.get("numberExists") and _jid_valido(encontrado):
                return encontrado
    except Exception:
        app.logger.warning("WAHA check-exists indisponível; usando número cadastrado")
    return "55" + telefone + "@c.us"


# Inicia pelo site autenticado a ativacao de UMA conta, enviando mensagem WAHA.
@app.route("/whatsapp/ativar", methods=["POST"])
def whatsapp_ativar_sem_codigo():
    conta, erro = _conta_configuravel()
    if erro:
        return erro
    if not conta["autorizado"]:
        return jsonify({"mensagem": "Autorize o WhatsApp nesta conta antes de continuar."}), 403

    usuario = descobre_id_usuario()
    cursor = con.cursor()
    try:
        cursor.execute("SELECT TELEFONE FROM USUARIO WHERE ID_USUARIO = ?", (usuario,))
        linha = cursor.fetchone()
    finally:
        cursor.close()
    telefone = _normalizar_telefone(linha[0] if linha else None)
    if not telefone:
        return jsonify({"mensagem": "Atualize o telefone cadastrado antes de ativar."}), 422
    try:
        _credenciais_waha()
    except RuntimeError:
        return jsonify({"mensagem": "O WhatsApp do Arkhé ainda não foi configurado no servidor."}), 503

    pendencia = {"id_usuario": int(usuario), "id_conta": int(conta["id_conta"]), "telefone": telefone}
    chave = _chave_pendente(telefone)
    chat_id = _descobrir_chat_destino(telefone)
    chave_chat = _chave_pendente_chat(chat_id)

    try:
        redis_cli = _redis_wa()
        with redis_cli.pipeline(transaction=True) as pipe:
            pipe.set(chave, json.dumps(pendencia), ex=PENDENCIA_TTL)
            pipe.set(chave_chat, json.dumps(pendencia), ex=PENDENCIA_TTL)
            pipe.execute()
    except Exception:
        app.logger.exception("Falha Redis ao iniciar ativação do WhatsApp")
        return jsonify({"mensagem": "Não foi possível preparar a ativação. Confira o Redis."}), 503

    try:
        url, headers = _credenciais_waha()
        resposta = requests.post(url + "/api/sendText",
            headers={**headers, "Content-Type": "application/json"},
            json={"session": "arkhe", "chatId": chat_id,
                  "text": ("Olá! Aqui é o assistente do Banco Arkhé. Você solicitou a ativação do WhatsApp pelo nosso site. "
                           "Para confirmar este número, responda ATIVAR. A solicitação expira em 10 minutos. "
                           "Se não foi você, ignore esta mensagem.")}, timeout=12)
        resposta.raise_for_status()
    except Exception:
        app.logger.exception("Falha no envio da mensagem de ativação pelo WAHA")
        try:
            redis_cli.delete(chave, chave_chat)
        except Exception:
            app.logger.warning("Não foi possível limpar ativação pendente após erro de envio")
        return jsonify({"mensagem": "Não foi possível enviar a mensagem de ativação agora."}), 503

    return jsonify({"enviado": True, "telefone_final": telefone[-4:],
                    "mensagem": "Mensagem enviada! Responda ATIVAR no seu WhatsApp em até 10 minutos."})


# Confirma a resposta ATIVAR e inclui a conta no vinculo Redis do remetente.
@app.route("/internal/whatsapp/confirmar", methods=["POST"])
def whatsapp_confirmar_sem_codigo():
    if not _servico_valido():
        return jsonify({"mensagem": "Serviço não autorizado."}), 401
    dados = request.get_json(silent=True) or {}
    chat_id = str(dados.get("chatId", ""))
    if not _jid_valido(chat_id):
        return jsonify({"confirmado": False, "mensagem": "Não foi possível identificar a conversa do WhatsApp."}), 403

    try:
        # Mesmo com um vinculo existente, uma nova ativacao deve adicionar a conta.
        redis_cli = _redis_wa()
        pendencia_chat = redis_cli.get(_chave_pendente_chat(chat_id))
        pendencia = json.loads(pendencia_chat) if pendencia_chat else None
        # Se o convite foi criado antes desta atualização, resolver @lid pelo WAHA.
        telefone = pendencia.get("telefone") if pendencia else _resolver_lid_pelo_waha(chat_id)
        if not telefone:
            return jsonify({"confirmado": False, "mensagem": "Não consegui identificar seu número pelo WhatsApp. Solicite um novo convite no site do Arkhé."}), 403

        chave = _chave_pendente(telefone)
        valor = redis_cli.get(chave)
        if not valor:
            if _conta_vinculada(chat_id):
                return jsonify({"confirmado": True, "ja_ativo": True,
                                "mensagem": "Seu WhatsApp ja esta vinculado ao Arkhé."})
            return jsonify({"confirmado": False, "mensagem": "Sua ativação expirou ou já foi concluída. Se necessário, solicite outra pelo site do Arkhé."}), 404
        pendencia_atual = json.loads(valor)
        # Caso tenha sido iniciado outro convite, nunca aceitar um vínculo antigo.
        if pendencia and pendencia != pendencia_atual:
            return jsonify({"confirmado": False, "mensagem": "Há uma ativação mais recente. Solicite outra mensagem no site."}), 409

        cursor = con.cursor()
        try:
            cursor.execute("""SELECT C.WHATSAPP_AUTORIZADO, C.WHATSAPP_NIVEL, U.TELEFONE
                FROM CONTA C INNER JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
                WHERE C.ID_CONTA = ? AND C.ID_USUARIO = ?""",
                (pendencia_atual["id_conta"], pendencia_atual["id_usuario"]))
            conta = cursor.fetchone()
        finally:
            cursor.close()
        if not conta or not conta[0] or _normalizar_telefone(conta[2]) != telefone:
            return jsonify({"confirmado": False, "mensagem": "A autorização foi revogada ou o telefone cadastrado mudou."}), 403

        _guardar_vinculo(chat_id, pendencia_atual["id_usuario"],
                         pendencia_atual["id_conta"], telefone, redis_cli)
        redis_cli.delete(chave, _chave_pendente_chat(chat_id))
        return jsonify({"confirmado": True, "nivel": int(conta[1]),
                        "mensagem": "WhatsApp ativado com sucesso! Esta conta foi vinculada."})
    except ValueError:
        return jsonify({"confirmado": False, "mensagem": "WhatsApp vinculado a outra identidade. Revogue a anterior."}), 403
    except Exception:
        app.logger.exception("Falha ao confirmar ativação WhatsApp")
        return jsonify({"confirmado": False, "mensagem": "Não foi possível concluir a ativação agora. Tente novamente em instantes."}), 503
