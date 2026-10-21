# Autenticacao WhatsApp / MAURO — versao de preparacao

Esta implementacao nao substitui a autenticacao convencional de terceiros e nao cria MCP.
O backend continua usando Firebird para dados bancarios; Redis guarda vinculos confirmados,
ativacoes temporarias e a conta selecionada para a conversa.

## Como autenticar a conversa

1. Titular entra no site, seleciona a conta e configura `WHATSAPP_AUTORIZADO` e `WHATSAPP_NIVEL`.
2. `POST /whatsapp/ativar` exige a sessao do site, cria pendencia de 10 minutos no Redis e envia pelo WAHA a mensagem para responder ATIVAR.
3. O n8n, depois de receber uma mensagem real do WAHA, chama `POST /internal/whatsapp/confirmar`, autenticado com `X-Arkhe-N8N-Key` e `chatId`. O backend verifica pendencia, telefone e permissao atual.
4. O Redis guarda `id_usuario`, `id_conta` selecionada e `contas_vinculadas`; uma nova ativacao do mesmo usuario acrescenta a conta sem apagar as anteriores.
5. `POST /internal/whatsapp/contexto` lista as contas explicitamente vinculadas **que continuam autorizadas no Firebird**. Se a conta ativa foi desativada, exige selecionar outra.
6. `POST /internal/whatsapp/selecionar-conta` exige `chatId` e `id_conta`; nao aceita uma conta nao vinculada. Nao cria autorizacao.

**Identidade**: o numero de WhatsApp deve corresponder ao numero do usuario que iniciou a ativacao no site. O mesmo numero nao autoriza contas de outro ID_USUARIO automaticamente.

**ATENCAO**: o n8n e um servico confiavel com a chave `N8N_SERVICE_KEY`; `chatId` deve ser extraido exclusivamente de evento verdadeiro do WAHA. Nao fornecer ferramentas de HTTP livre para o modelo gerar `chatId`, headers de autenticacao ou `id_conta`. Proteger o webhook do n8n contra chamadas falsas, inclusive com controles de origem/assinatura quando disponiveis. Chaves do n8n e de integracoes nunca devem ir para a resposta da IA.

## Autenticacao central das rotas bancarias

A funcao `autenticar_requisicao(nivel_whatsapp=1, permitir_whatsapp=False)` em `api/common.py`:

- Se ha `X-Client-ID`/`X-Client-Secret`, usa **a autenticacao convencional original**, sem consultar WHATSAPP_NIVEL.
- Se o endpoint permite o canal e ha `X-Arkhe-N8N-Key` mais `X-Arkhe-Chat-ID`, valida a chave de servico, o vinculo, a conta ativa, o telefone e o nivel atual no Firebird.
- Nao aceita misturar os dois modelos de autenticacao na mesma chamada.
- Se a conta foi desativada no Firebird, uma consulta subsequente retorna 403.

Exemplo, **apenas entre n8n confiavel e backend**:

```http
GET /api/v1/saldo
X-Arkhe-N8N-Key: <segredo-do-servico>
X-Arkhe-Chat-ID: <jid-validado-do-evento-waha>
```

As rotas GET existentes de contas e cobrancas autorizam nivel 1.
Criar cobranca Pix e emitir boleto pela API existente autoriza nivel 3 no canal WhatsApp (conta PJ).
`POST /api/v1/vendas/cartao` continua exclusivamente para integracoes externas com Client ID e Secret.

**Esta versao NAO habilita pagamentos de saida** (Pix enviado, DDA ou folha): essas operacoes exigem implementacao de API e protecoes adicionais, inclusive idempotencia, limites e auditoria. Elas nao devem ser liberadas apenas por adicao de um header ou alteracao de `nivel_whatsapp`.

## Redis: formato e compatibilidade

Prefixo de vinculo existente: `arkhe:wa:binding:v1:` + SHA-256 do chatId.
Formato antigo:
```json
{"id_usuario": 7, "id_conta": 10, "telefone": "11999999999", "chat_id": "5511999999999@c.us"}
```
Novo formato:
```json
{"id_usuario": 7, "id_conta": 20, "contas_vinculadas": [10, 20], "telefone": "11999999999", "chat_id": "5511999999999@c.us"}
```
A leitura aceita os dois formatos; ao ativar outra conta, salva o segundo.
`id_conta` e a conta selecionada, `contas_vinculadas` e a lista de contas que foram efetivamente ativadas.
Somente as contas que ainda estiverem autorizadas no Firebird sao exibidas/aceitas.

A ativacao pendente dura 600 segundos, o vinculo dura 30 dias. Selecionar conta preserva o tempo restante, sem renovar a autorizacao. Reativar uma conta renovara os 30 dias.

Consultas seguras no redis-cli:

```redis
SCAN 0 MATCH arkhe:wa:binding:v1:* COUNT 100
TTL arkhe:wa:binding:v1:<hash-da-chave-encontrada>
GET arkhe:wa:binding:v1:<hash-da-chave-encontrada>
```

NAO usar FLUSHALL/FLUSHDB. Nao compartilhar valores completos de vinculo em logs publicos.

## Contratos internos

- `POST /internal/whatsapp/contexto` com `{"chatId":"..."}`
  retorna `{"vinculado":true,"id_usuario":7,"conta_selecionada":20,"nivel":3,"selecao_necessaria":false,"contas":[{"id_conta":10,"tipo_conta":0,"nivel":2},{"id_conta":20,"tipo_conta":1,"nivel":3}]}`.
- `POST /internal/whatsapp/selecionar-conta` com `{"chatId":"...","id_conta":10}`
  retorna `{"selecionada":true,"id_conta":10,"nivel":2}`.
- Os dois exigem `X-Arkhe-N8N-Key`. Nao sao endpoints publicos de integracao.

## Validacao antes de producao

Executar `python -m unittest discover -s tests -p 'test_whatsapp_vinculos.py'` no ambiente com dependencias instaladas.
Depois executar os demais testes em banco Firebird temporario, sem tocar no banco real.

Testar manualmente em homologacao: ativar PF, ativar PJ no mesmo WhatsApp, listar, alternar,
desativar uma das contas pelo site, recusar chave invalida, expirar vinculo, testar `@c.us` e `@lid` no WAHA e garantir que o workflow nao permita falsificar origem.

**Observacao de versionamento:** esta branch foi criada a partir da `main` remota que ainda nao tinha os sete novos endpoints reportados pelo Codex local. Antes de integrar, reconciliar o codigo local atualizado para nao sobrescrever seus endpoints novos.
