# WhatsApp Arkhé — vínculo persistente (etapa 1)

**Status:** branch experimental, não implantada. Este módulo NÃO fornece consultas MCP nem movimentação financeira.

## Motivo

WAHA GOWS pode entregar mensagens com remetente `@lid` em vez de `@c.us`. Não é seguro obter a identidade bancária retirando números de um LID. O vínculo deve nascer de uma ação do usuário autenticado no banco.

## Fluxo previsto

1. O cliente entra no Arkhé, seleciona a conta e habilita consultas WhatsApp usando a configuração Nível 1 existente.
2. O frontend chama `POST /whatsapp/vinculo/criar` sob a sessão web e a política Origin existente. O retorno tem `mensagem_inicial: "ARKHE VINCULAR <token>"` válida por dez minutos.
3. O frontend abre o chat com `https://wa.me/<numero-do-atendimento>?text=<mensagem_inicial codificada>`. Não adicionar tokens à URL de callback do backend.
4. WAHA envia a mensagem ao n8n via webhook autenticado. O n8n lê **o JID do remetente** e o token do corpo, chama `POST /internal/whatsapp/vinculo/confirmar` com `{ "chat_id": "numero@lid", "token": "..." }` e segredo `X-Arkhe-N8N-Key`.
5. O token é de uso único, armazenado por SHA-256 e expira após 10 minutos. O vínculo persiste em `WHATSAPP_IDENTIDADE`. O n8n pode consultar `POST /internal/whatsapp/vinculo/contas` para obter apenas as contas que continuam autorizadas.
6. `POST /whatsapp/vinculo/revogar` revoga a identidade e as sessões WhatsApp antigas do usuário autenticado.

## Dependências

- **Não executar** a migração nova sem antes realizar backup e aplicar/verificar `migrations/20261019_whatsapp_config.sql`.
- Executar `migrations/20261019_whatsapp_vinculo.sql` somente em ambiente de testes primeiro.
- O frontend ainda não chama estes novos endpoints.
- O workflow n8n ainda não identifica mensagens de vínculo nem seleciona conta usando a nova identidade.
- O MCP ainda usa sessões de telefone/código da versão anterior: **não usar o novo vínculo como autenticação MCP até substituir e testar a autorização ponta a ponta**.
- `WHATSAPP_IDENTIDADE` associa um chat a um único usuário. Uma conta adicional desse mesmo usuário passa pelo consentimento individual `WHATSAPP_CONFIG`.
- O n8n deve validar origem do webhook, bloquear mensagens próprias, impedir grupos, não armazenar token de vínculo em histórico/prompt e nunca entregar este token ao Gemini.
- Operações de Pix, pagamento de boletos, folha e outras operações de débito estão fora do escopo desta etapa.

## Próxima implementação obrigatória

1. Criar endpoint de seleção de conta que recebe o chat vinculado e um identificador de conta pertencente ao usuário; persistir contexto da conversa de forma revogável.
2. Trocar a emissão de sessão MCP baseada somente no telefone por uma sessão derivada do vínculo e da conta selecionada, verificada em CADA consulta pelo backend.
3. Adaptar dashboard para autorização/vinculação e workflow n8n para `@lid`.
4. Testes de integração com Firebird: token expirado/reutilizado, `@lid` diferente, duas pessoas no mesmo chat, PJ bloqueada, revogação, seleção cruzada PF/PJ e concorrência.
5. Só depois adicionar Gemini como orquestrador das consultas. Nunca permitir transações financeiras por comando do modelo sem confirmação bancária independente.
