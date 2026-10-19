# WhatsApp Arkhé — ligação do n8n com convite do site

## Configuração do backend no EasyPanel
Defina `ARKHE_WHATSAPP_NUMBER` com o número oficial do WAHA no formato 55DDDNUMERO, só dígitos.
Defina `N8N_SERVICE_KEY` com um segredo novo, longo e aleatório no backend.
Configure **o mesmo segredo** no n8n por credencial/variável segura. Nunca coloque o segredo num nó Code, no frontend ou no GitHub.

## Fluxo atual
Preserve o webhook WAHA, Gemini e memória Redis. A entrada `Preparar mensagem` deve produzir `chatId` confiável a partir do evento WAHA, e o texto recebido.

Antes de enviar a mensagem de ativação ao Gemini:

1. Use um **IF** para detectar mensagens contendo `Codigo: ` e separar a etapa de convite da conversa comum.
2. Extraia o código **somente da mensagem recebida** e o `chatId` **do envelope original do WAHA**. Nunca permita que o Gemini determine/remodele o chatId.
3. Na ramificação do convite, adicione **HTTP Request**:
   - Method: `POST`
   - URL: `https://<ENDERECO-REAL-DO-BACKEND>/internal/whatsapp/validar-convite`
   - Headers: `X-Arkhe-N8N-Key` (credencial secreta); `Content-Type: application/json`.
   - JSON body: `{"chatId":"<chatId-do-WAHA>","codigo":"<codigo-extraido>"}`.
4. Se o backend responder `convite_validado: true`, o n8n pode enviar uma **saudação de convite confirmado**, mas deve deixar claro que **consultas bancárias e pagamentos ainda não foram liberados**.
5. Se houver erro, responda com a mensagem de falha sem repassar dados de sessão ao Gemini.
6. Mensagens comuns continuam no fluxo Gemini+Redis **sem ferramentas de saldo, Pix ou contas**.

## Segurança
- Os campos `WHATSAPP_AUTORIZADO` e `WHATSAPP_NIVEL` são apenas autorização por CONTA.
- O token de convite expira em 10 minutos. Seu uso valida um convite e um telefone; **não cria sessão bancária nem vínculo permanente**.
- `@lid` é recusado pela verificação atual, até existir normalização de identidade verificada pelo provedor.
- Não persistimos JID no Firebird porque a estrutura aprovada não possui local para isso; não usar Redis de memória de chat como fonte de autorização.
- Não conectar as rotas MCP a esse fluxo até implementar a associação persistente de identidade e validação de permissões por requisição.
