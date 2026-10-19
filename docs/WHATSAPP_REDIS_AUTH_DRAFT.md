# WhatsApp Arkhé — autorização Redis (rascunho, NÃO implantar em produção)

Escopo: vínculo de conversa e autorização por usuário/conta para desenvolvimento. Não inclui consulta MCP autenticada, autorização granular de cada ação, transações, nem confirmação Pix. O workflow Gemini em execução deve continuar SEM ferramentas bancárias até completar esses controles.

## Configuração backend
- `REDIS_URL`: URL interna do Redis com autenticação, e armazenamento persistente, sem expor à Internet. Pode compartilhar a infraestrutura Redis do n8n com namespace isolado de chaves.
- `N8N_SERVICE_KEY`: segredo longo exclusivo compartilhado com o serviço n8n (header `X-Arkhe-N8N-Key`). Não usar chave WAHA nem GitHub.
- Instalar `redis` do requirements.txt e disponibilizar os valores apenas como secrets no EasyPanel.

## Fluxo previsto
1. O usuário autenticado no site escolhe uma conta e chama `POST /whatsapp/autorizacao` com JSON `{"nivel": 1}`, `2` ou `3`. **O nível é teto, não cria poderes de cargo.**
2. O site chama `POST /whatsapp/vinculo` e apresenta o código de uso único (10 min). O front ainda precisa ser implementado.
3. O usuário envia esse código na conversa do número WAHA. O n8n precisa reconhecer a mensagem e chamar `POST /internal/whatsapp/vincular` com `{"chat_id":"...@lid","codigo":"..."}`, assinada pelo header de serviço.
4. A cada mensagem, o n8n chama `POST /internal/whatsapp/contexto` com `{"chat_id":"...@lid"}` e obtém somente as contas com autorização ativa e acesso real em `ACESSO_CONTA`.
5. O n8n permite seleção de conta apenas dentro dessa lista. Escolha armazenada no Redis como contexto, NUNCA como permissão.
6. Para revogar uma conta, o usuário autenticado chama `DELETE /whatsapp/autorizacao` na conta selecionada.

## Pendências antes de produção
- Revisar proteção CSRF do site e controle de sessão; adicionar confirmação de identidade recente para alteração de nível.
- Implementar e testar fluxo de login/vínculo, frontend, throttle de tentativas por chat e limitações por cargo.
- Validar disponibilidade Redis, volume persistente, ACL, backups e rotação de segredo.
- Adicionar testes integrados com Redis e Firebird de teste; nada foi executado contra produção.
- Ainda **não** gerar sessão MCP a partir da saída de `contexto`; adicionar um broker confiável que verifique escopo, cargo e conta a cada ferramenta. Nível 3 NÃO habilita movimentação por si só.
- Processamento de transações requer estado de confirmação estruturado e proteção contra repetição, não só histórico do Gemini.
- Revisar o endpoint antigo `/internal/whatsapp/iniciar` antes de liberar uso bancário, pois reconhece usuários só por telefone.

Sem migrações SQL e sem alterações no esquema Firebird.
