# Arquitetura das APIs do Arkhé

Referência interna de manutenção do backend. Rotas `/internal/...` não fazem parte da API pública.

## Organização

```text
api/
├── __init__.py   # importa os módulos e registra as rotas
├── common.py     # autenticação da integração e helpers compartilhados
├── get.py        # endpoints GET da API
├── post.py       # endpoints POST da API e consulta legada do WhatsApp
├── put.py        # sem endpoints de integração PUT no momento
├── delete.py     # sem endpoints de integração DELETE no momento
├── patch.py      # sem endpoints de integração PATCH no momento
└── whatsapp.py   # configuração, ativação, vínculo, identidade e permissões
```

`main.py` importa `api` depois de criar a aplicação Flask. A lógica bancária e os demais endpoints continuam nos módulos originais (`conta.py`, `transferencia.py`, `pix.py`, `cartao.py`, `folha.py` e outros). `api.common` centraliza os helpers compartilhados; `api.valor_monetario_api` continua exportado para os módulos bancários que já o importavam.

## API de integração

Os caminhos, métodos e contratos abaixo são usados por integrações existentes. `/api/v1/...` exige `X-Client-ID` e `X-Client-Secret`; cada credencial permanece vinculada à conta cadastrada para aquele `client_id`.

| Método | Caminho | Acesso |
| --- | --- | --- |
| GET | `/api/v1/conta` | Credenciais da integração |
| GET | `/api/v1/saldo` | Credenciais da integração |
| GET | `/api/v1/movimentacoes` | Credenciais da integração; aceita `data_inicio` e `data_fim` |
| GET | `/api/v1/resumo-financeiro` | Credenciais da integração; aceita `data_inicio` e `data_fim` |
| POST | `/api/v1/cobrancas/pix` | Credenciais da integração |
| POST | `/api/v1/cobrancas/pix/qrcode` | Credenciais da integração; alias existente |
| GET | `/api/v1/cobrancas/pix/<id_cobranca>` | Credenciais da integração; somente cobrança da conta vinculada |
| POST | `/api/v1/cobrancas/boletos` | Credenciais da integração |
| GET | `/api/v1/cobrancas/boletos/<id_cobranca>` | Credenciais da integração; somente cobrança da conta vinculada |
| GET | `/api/v1/cobrancas/boletos/<id_cobranca>/pdf` | Credenciais da integração; somente cobrança da conta vinculada |
| POST | `/api/v1/vendas/cartao` | Credenciais da integração + `X-Idempotency-Key` (8–128 caracteres) |

Todas as rotas `/api/v1/...` autenticadas por `X-Client-ID` e `X-Client-Secret`
aplicam uma cota compartilhada por integração no Redis: padrão de 120 requisições
a cada 60 segundos. É possível configurar `ARKHE_API_RATE_LIMIT` e
`ARKHE_API_RATE_WINDOW_SECONDS`; o Redis é lido de `REDIS_URL`. Ao exceder a cota,
a API retorna `429`, `codigo=RATE_LIMIT_EXCEEDED` e o cabeçalho `Retry-After`.
Se Redis ou a configuração estiver indisponível, a autenticação da API falha
fechada com `503`. Esse controle não altera os endpoints nem os limites próprios
do WhatsApp.

Vendas de cartão gravam a chave, a compra, a movimentação e a resposta no mesmo
commit Firebird. Repetir a mesma chave e os mesmos parâmetros devolve a resposta
original; reutilizar a chave com outro conteúdo retorna `409`. Gere uma chave nova
para cada venda e reutilize-a somente ao repetir a mesma solicitação após falha de
rede. Compras legítimas com o mesmo cartão, valor e estabelecimento são aceitas
quando têm chaves distintas. O servidor não usa proximidade de horário como prova
de duplicidade.

Gerenciamento das credenciais permanece protegido pela sessão bancária:

| Método | Caminho | Acesso |
| --- | --- | --- |
| GET | `/integracoes/api` | Sessão bancária da conta |
| POST | `/integracoes/api` | Sessão bancária; criação disponível para conta PJ |
| POST | `/integracoes/api/<id_integracao>/regenerar-secret` | Sessão bancária da conta proprietária |

## WhatsApp e uso interno

`api/whatsapp.py` concentra configuração da conta, ativação, convites, vínculo do remetente e consulta das permissões atuais. Mantém as verificações existentes de sessão bancária, titular, `N8N_SERVICE_KEY`, WAHA, Redis e autorização por conta.

- Sessão bancária: `GET/PUT /whatsapp/configuracao`, `POST /whatsapp/link` e `POST /whatsapp/ativar`.
- Serviço n8n autenticado por `X-Arkhe-N8N-Key`: `POST /internal/whatsapp/contexto`, `/internal/whatsapp/validar-convite` e `/internal/whatsapp/confirmar`.
- `POST /internal/whatsapp/iniciar` e `/internal/whatsapp/selecionar-conta` são caminhos legados desativados que sempre retornam `403`.
- `POST /internal/whatsapp/consulta` permanece em `api/post.py`. Valida o vínculo em Redis e a autorização atual antes de consultar saldo/extrato; a lógica financeira fica fora de `api/whatsapp.py`.

O n8n será reconstruído para consumir a API convencional. Esta etapa não cria uma nova autenticação entre o n8n e a API nem usa uma chave global como autorização irrestrita por conta. Não divulgar as rotas internas do WhatsApp na documentação pública.

## Novas operacoes de pagamento (PR #4)

A branch `feat/whatsapp-multicontas-autorizacao` adiciona:

| Metodo | Caminho | Permissao |
| --- | --- | --- |
| GET | `/api/v1/dda` | Conta autenticada; WhatsApp nivel 1 |
| POST | `/api/v1/pagamentos/pix` | Conta autenticada; WhatsApp nivel 2 ou integracao externa habilitada |
| POST | `/api/v1/pagamentos/dda/<id_cobranca>` | Boleto DDA pertencente a conta pagadora; WhatsApp nivel 2 ou integracao habilitada |

Os dois POST exigem `X-Idempotency-Key`. A API nao aceita `id_conta` do cliente para
selecionar pagador. Clientes externos ja existentes nao ganham permissao de pagamento
automaticamente: habilitar seus Client IDs explicitamente em
`ARKHE_API_PAGAMENTOS_CLIENT_IDS`. Sem Redis, pagamentos retornam indisponibilidade
antes de realizar transferencia. Para WhatsApp, `ARKHE_WHATSAPP_LIMITE_PAGAMENTO`
define o teto individual por transacao (padrao R$ 1.000,00). Os testes de Redis e
multicontas sao isolados; testar com Firebird temporario antes de publicar.

Para detalhes de identidade, consultas, limites e exemplo de request, consulte
`docs/WHATSAPP_AUTORIZACAO.md`.

**Cuidado ao integrar:** a main remota pode estar atrasada em relacao ao checkout local.
Os sete endpoints implementados pelo Codex local devem ser preservados e conciliados
antes de fazer merge desta PR.

## Adicionar uma rota

1. Coloque a função no módulo do método HTTP (`get.py`, `post.py`, `put.py`, `delete.py` ou `patch.py`).
2. Preserve caminhos e métodos de contratos existentes; documente qualquer endpoint novo.
3. Reutilize `api.common` quando autenticação ou validação forem compartilhadas. Mantenha as regras bancárias no módulo de domínio correspondente.
4. Preserve autenticação e autorização em rotas internas. Não exponha rotas administrativas, financeiras ou de funcionários usando credenciais globais.
5. Verifique inicialização, duplicidade de método/caminho e testes relacionados sem chamar serviços reais nem executar operações financeiras.
