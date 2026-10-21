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

### Pagamentos agora incluidos na branch

- `GET /api/v1/dda`: lista ate 50 boletos pendentes destinados a conta autenticada (nivel WhatsApp 1).
- `POST /api/v1/pagamentos/pix`: realiza Pix de saida pela chave informada (nivel WhatsApp 2).
- `POST /api/v1/pagamentos/dda/<id_cobranca>`: paga apenas boleto DDA com pagador igual a conta autenticada e status pendente (nivel WhatsApp 2).

No WhatsApp nao e exigido novo PIN por pagamento, conforme a experiencia prevista; ha limite preventivo por operacao (`ARKHE_WHATSAPP_LIMITE_PAGAMENTO`, padrao R$ 1.000,00). **O nivel 2 nao deve ser entendido como autenticacao forte**: proteja WAHA/n8n, audite operacoes e disponibilize revogacao da conta pelo site.

Sistemas externos podem usar essas novas rotas pela autenticacao normal somente apos o Client ID ser habilitado no ambiente `ARKHE_API_PAGAMENTOS_CLIENT_IDS`. Nenhum segredo antigo ganha automaticamente permissão para enviar dinheiro. Nao alterar a documentacao visual do frontend.

Ambos os POST exigem `X-Idempotency-Key` de 8 a 128 caracteres, unico por operacao; a chave deve ser gerada pelo integrador/n8n de maneira que um retry da mesma operacao reutilize a mesma chave e uma operacao distinta use outra. O backend usa `SET NX` no Redis para impedir chamadas simultaneas, salva a resposta por sete dias e nao executa se Redis estiver fora. Falhas apos COMMIT podem gerar resultado indeterminado, requerendo consultar extrato antes de qualquer novo envio. **Sem uma referencia transacional persistente e unica no Firebird, esta versao nao garante idempotencia eterna se o Redis for apagado/expirar**.

```http
POST /api/v1/pagamentos/pix
X-Arkhe-N8N-Key: <segredo>
X-Arkhe-Chat-ID: <jid-waha-validado>
X-Idempotency-Key: <id-unico-da-operacao>
Content-Type: application/json

{"tipo_chave": "cpf", "chave_pix": "52998224725", "valor": "25.00"}
```

```http
POST /api/v1/pagamentos/dda/123
X-Arkhe-N8N-Key: <segredo>
X-Arkhe-Chat-ID: <jid-waha-validado>
X-Idempotency-Key: <id-unico-da-operacao>
Content-Type: application/json

{}
```

Pagamento de folha, cartao e qualquer outra saida nao foram habilitados por este patch. O frontend original segue usando suas rotas antigas.

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
  retorna `{"vinculado":true,"id_usuario":7,"conta_selecionada":20,"nivel":3,"selecao_necessaria":false,"contas":[{"id_conta":10,"tipo_conta":0,"nivel":2,"descricao":"Conta pessoal","conta_final":"0010"},{"id_conta":20,"tipo_conta":1,"nivel":3,"descricao":"Empresa ficticia","conta_final":"0020"}]}`.
- `POST /internal/whatsapp/selecionar-conta` com `{"chatId":"...","id_conta":10}`
  retorna `{"selecionada":true,"id_conta":10,"nivel":2}`.
- Os dois exigem `X-Arkhe-N8N-Key`. Nao sao endpoints publicos de integracao.

## Validacao antes de producao

Executar `python -m unittest discover -s tests -p 'test_whatsapp_vinculos.py'` no ambiente com dependencias instaladas.
Depois executar os demais testes em banco Firebird temporario, sem tocar no banco real.

Testar manualmente em homologacao: ativar PF, ativar PJ no mesmo WhatsApp, listar, alternar,
desativar uma das contas pelo site, recusar chave invalida, expirar vinculo, testar `@c.us` e `@lid` no WAHA e garantir que o workflow nao permita falsificar origem.

****Observacao de versionamento:** para não depender do checkout local do Codex, a branch reconstrói seis consultas e uma verificação de CPF/CNPJ com base nas rotas e tabelas da main. Os caminhos adotados devem ser comparados com o checkout original quando estiver disponível, mas o código remoto não depende mais dele.


## Sete endpoints reconstruidos a partir da main remota

- `GET /api/v1/chaves-pix`: chaves da conta autenticada.
- `GET /api/v1/cartao`: cartão sem PAN completo nem CVV.
- `GET /api/v1/cartao/compras`: compras da conta, com limite de 50.
- `GET /api/v1/cartao/faturas`: lista de faturas, até 30.
- `GET /api/v1/cartao/faturas/<id_fatura>`: detalhe validando titularidade.
- `GET /api/v1/cartao/limites`: limite total, utilizado, disponível.
- `POST /api/v1/contas/verificar-documento`: retorna somente `possui_conta`,
  com validacao de CPF/CNPJ inclusive alfanumerico e quota por integração de
  5 verificacoes/minuto e 50/dia, controlada em Redis com operacao atomica.

As consultas permitem WhatsApp nivel 1 e a API de integracoes convencional.
A verificacao de existencia de conta permanece exclusivamente disponivel a
integracoes externas autenticadas, sem acesso pelo MAURO.

**Importante:** a reconstrucao nao equivale a prova de compatibilidade com os
sete endpoints nao publicados do checkout local do Codex. Os caminhos podem ser
diferentes; nao trocar contratos de terceiros sem comparar. Revisao e testes
contra Firebird de teste ainda sao obrigatorios antes do deploy.
