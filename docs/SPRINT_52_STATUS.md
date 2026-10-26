# Main Sprint Arkhé — auditoria dos 52 requisitos

**Checkpoint inicial: 2026-10-26.** Esta matriz registra o estado do código nos repositórios no momento da leitura. Ela não certifica funcionamento na produção.

## Fonte e método

- HEADs lidos antes de qualquer edição: backend `61eccdf6a88f70510ca2fec9eed8e7f97f05698e`; web `7b47ec0fa52f9f5148849dba8d43cc1ecdf09848`; Expo `45f1e704d9e460fd899975ac9073e4423205c466`. Os três estavam limpos e sincronizados com `origin/main`.
- A planilha literal dos 52 requisitos não está no protótipo PPTX de 25 slides. A lista usada aqui é a reconstrução `.codex-pptx-build/requirements-52.mjs`, reconciliada com os requisitos que o usuário já descreveu na conversa. Pendência: confirmar o texto final contra o enunciado oficial da sprint se houver outro arquivo-fonte.
- Foram pesquisados os módulos Flask, migrações, rotas, páginas web, app Expo e testes versionados. “Implementado no código” não significa “publicado e validado”. A produção não foi consultada nesta auditoria inicial; não houve acesso ao Firebird online nem operação financeira.
- A matriz abaixo mostra evidência estática e os testes existentes; a coluna de teste não declara aprovação sem execução.

## Matriz
### 01. Pedir dados que faltam

- **Solicitado:** A IA deve solicitar os dados faltantes antes de preparar uma operação.
- **Evidência localizada:** back_arkche/mauro_pix.py · criar/atualizar proposta; back_arkche/assistente_mauro.py · intenção; web/AssistenteMauro.jsx · cartão de proposta.
- **Endpoints/integrações:** POST /api/v1/assistente/conversas/<id>/mensagens; POST .../pix/propostas/<id>/confirmar|cancelar
- **Persistência/objetos:** MAURO_CONVERSA, MAURO_MENSAGEM, proposta Pix from migration 009
- **Frontend/mobile:** arkhe-web/src/components/Mauro/AssistenteMauro.jsx; Expo: no MAURO screen found
- **Testes existentes:** test_assistente_mauro_intencoes.py e test_mauro_pix_seguro.py existem no repositório; não foram executados nesta produção.
- **Estado inicial:** PARCIAL · coleta e proposta Pix existem; pedidos genéricos de escrita não são CRUD universal.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Gravação e fluxo ao vivo não realizados neste trabalho; nenhuma operação financeira foi confirmada.

### 02. Resumo antes da confirmação

- **Solicitado:** A IA deve apresentar resumo da operação antes da confirmação do cliente.
- **Evidência localizada:** back_arkche/mauro_pix.py · preparar proposta; arkhe-web/src/components/Mauro/AssistenteMauro.jsx · resumo e botões.
- **Endpoints/integrações:** POST /api/v1/assistente/conversas/<id>/mensagens; proposal confirmation routes registered by mauro_pix.py
- **Persistência/objetos:** Pix proposal table from migration 009; bank movement tables are not written before confirmation
- **Frontend/mobile:** arkhe-web/src/components/Mauro/AssistenteMauro.jsx
- **Testes existentes:** test_mauro_pix_seguro.py cobre estados/escopo da proposta; não houve confirmação real nesta produção.
- **Estado inicial:** IMPLEMENTADO NO FLUXO PIX · produção não revalidada nesta tarefa.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** O cartão de proposta comprova apresentação; não prova um Pix liquidado.

### 03. Auditar ações do MAURO

- **Solicitado:** Registrar em auditoria as ações relevantes executadas pelo agente de IA.
- **Evidência localizada:** back_arkche/assistente_mauro.py · registrar_evento_flask; back_arkche/auditoria.py · AUDITORIA_EVENTO_OUTBOX.
- **Endpoints/integrações:** POST /api/v1/assistente/conversas/<id>/mensagens; GET /api/v1/admin/auditoria and /stream
- **Persistência/objetos:** AUDITORIA_EVENTO_OUTBOX and separate AUDITORIA_EVENTO schema; migration 007
- **Frontend/mobile:** arkhe-web AdminBanco/Central de Auditoria components; no Expo audit UI
- **Testes existentes:** test_auditoria.py e test_mauro_pix_seguro.py; os testes não foram executados nesta apresentação.
- **Estado inicial:** CÓDIGO LOCALIZADO · cobertura de cada transição deve ser demonstrada em gravação.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não registrar PIN, token, senha ou conteúdo sensível; o feed ao vivo não foi capturado.

### 04. Auditar integrações externas

- **Solicitado:** Registrar ações de integrações e agentes externos; os requisitos antes descritos como MCP foram adaptados a REST.
- **Evidência localizada:** back_arkche/api/common.py · autenticar_integracao/autenticar_requisicao; back_arkche/auditoria.py · registrar_evento_flask.
- **Endpoints/integrações:** API routes in api/get.py, api/post.py, api/put.py; integration auth is in api/common.py
- **Persistência/objetos:** Integration API records plus audit outbox; audit completeness is partial
- **Frontend/mobile:** arkhe-web Integracoes and API docs
- **Testes existentes:** test_api_pagamentos_isolados.py e test_whatsapp_vinculos.py cobrem partes dos limites de acesso; cobertura integral de logs não foi medida.
- **Estado inicial:** PARCIAL · mecanismos existem; auditoria ponta a ponta de todo agente não foi revalidada.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Sem usar segredo real nem afirmar que todo cliente externo publica eventos em produção.

### 05. Detectar tentativas suspeitas

- **Solicitado:** Detectar tentativas de login suspeitas.
- **Evidência localizada:** back_arkche/conta.py · login_temporariamente_bloqueado/registrar_falha_login; back_arkche/auditoria.py · evento de login recusado.
- **Endpoints/integrações:** POST /login_usuario; POST /login
- **Persistência/objetos:** Redis counters/block TTL and login audit/notification events; no broad fraud table
- **Frontend/mobile:** arkhe-web Login; no real-user failure tests permitted
- **Testes existentes:** tests/test_login_bloqueio.py existe; os testes não foram reexecutados nesta tarefa.
- **Estado inicial:** PARCIAL · bloqueio por repetição localizado; detecção ampla de anomalia não demonstrada.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não tentar falhas com conta real nem chamar o bloqueio de fraude comprovada.

### 06. Limites diurnos e noturnos

- **Solicitado:** Configurar limites por operação e acumulados, PF/PJ, em 06h–21h59 e 22h–05h59 no horário de São Paulo.
- **Evidência localizada:** back_arkche/limites.py · aplicar_limite/_politica_efetiva; migration 010; arkhe-web/src/pages/Limites/Limites.jsx.
- **Endpoints/integrações:** GET /api/v1/limites; GET/PUT /api/v1/limites/conta/configuracao; GET/PUT /api/v1/limites/admin/politicas
- **Persistência/objetos:** POLITICA_LIMITE_OPERACAO, POLITICA_LIMITE_PERIODO, LIMITE_CONTA_OPERACAO/PERIODO, CONTROLE_LIMITE_CONTA
- **Frontend/mobile:** arkhe-web/src/pages/Limites/Limites.jsx
- **Testes existentes:** Há testes de limites e integração Firebird isolada; 45 aprovações foram reportadas no histórico, não repetidas aqui.
- **Estado inicial:** IMPLEMENTADO · UI de limites observada em sessão publicada, somente leitura; sem ajuste de valores.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** A sessão continha dados de conta; nenhum dado privado foi incluído no deck.

### 07. Agendar pagamentos e transferências

- **Solicitado:** Permitir agendamento de pagamentos e transferências.
- **Evidência localizada:** back_arkche/agendamentos.py · criar_agendamento/cancelar_agendamento/processar_agendamentos_pendentes; web/Agendamentos.jsx.
- **Endpoints/integrações:** GET/POST /api/v1/agendamentos; PATCH /api/v1/agendamentos/<id>/cancelar
- **Persistência/objetos:** AGENDAMENTO_PAGAMENTO and execution state in migration 004
- **Frontend/mobile:** arkhe-web/src/pages/Agendamentos/Agendamentos.jsx
- **Testes existentes:** Criação/cancelamento sem saldo foram relatados em sessões anteriores; teste do ciclo de execução não foi repetido.
- **Estado inicial:** PUBLICAÇÃO RELATADA · execução automática ponta a ponta não revalidada nesta tarefa.
- **Publicação/validação:** Há relato anterior de publicação, sem validação de produção nesta auditoria.
- **Ação/limite:** Não apresentar agendamento cancelado como execução concluída.

### 08. Pagamentos recorrentes

- **Solicitado:** Permitir pagamentos recorrentes com frequência e término configuráveis.
- **Evidência localizada:** back_arkche/recorrencias.py · criar/listar/atualizar/processar_recorrencias_pendentes; web/Recorrencias.jsx.
- **Endpoints/integrações:** GET/POST /api/v1/recorrencias; PUT /api/v1/recorrencias/<id>; PATCH pause/reactivate/cancel routes
- **Persistência/objetos:** RECORRENCIA_PAGAMENTO and links to AGENDAMENTO_PAGAMENTO in migration 005
- **Frontend/mobile:** arkhe-web/src/pages/Agendamentos/Recorrencias.jsx
- **Testes existentes:** Testes e operação online não foram repetidos nesta apresentação; o bloqueio de boleto está explícito no backend.
- **Estado inicial:** PARCIAL · Pix implementado; boleto recorrente permanece desabilitado por regra de validade.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não declarar recorrência de boleto funcional nem autorizar execução em nome do cliente.

### 09. Destinatários favoritos

- **Solicitado:** Salvar destinatários favoritos e permitir teto maior de transferência para favorito.
- **Evidência localizada:** back_arkche/favoritos.py · validar_favorito_selecionado/destinatario_esta_favoritado; back_arkche/limites.py · teto favorito.
- **Endpoints/integrações:** GET/POST /favoritos_pix; DELETE /favoritos_pix/<id>
- **Persistência/objetos:** FAVORITO_PIX from migration 003
- **Frontend/mobile:** Favorite Pix is in backend/frontend services; a dedicated user-facing favorite manager requires final path verification
- **Testes existentes:** test_limites.py e verificações de favoritos existem; resultado não foi reexecutado nesta entrega.
- **Estado inicial:** CÓDIGO LOCALIZADO · publicação e integração live não revalidadas aqui.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não usar chaves Pix ou destinatários de clientes reais.

### 10. Painel administrativo bancário

- **Solicitado:** Exibir usuários, contas, movimentações e áreas administrativas autorizadas.
- **Evidência localizada:** back_arkche/admin_banco.py · _acesso_admin/resumo_admin_banco; arkhe-web/src/pages/AdminBanco/AdminBanco.jsx; Limites.jsx.
- **Endpoints/integrações:** GET /api/v1/admin/banco/permissao, /resumo, /usuarios, /operacoes
- **Persistência/objetos:** Queries against USUARIO, CONTA, MOVIMENTACAO and current banking status columns
- **Frontend/mobile:** arkhe-web/src/pages/AdminBanco/AdminBanco.jsx
- **Testes existentes:** test_admin_banco.py existe; painel geral publicado e autorização ponta a ponta não foram testados nesta tarefa.
- **Estado inicial:** IMPLEMENTAÇÃO LOCALIZADA · autorização é de backend; validação live da dashboard geral pendente.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não bloquear contas nem executar ações administrativas reais para a gravação.

### 11. Preferências de notificações

- **Solicitado:** Permitir ativar/desativar categorias sem apagar eventos ou histórico.
- **Evidência localizada:** back_arkche/notificacoes.py · _preferencia_ativa/_registrar_evento; api/notificacoes.py; Dashboard/NotificacoesDashboard.jsx.
- **Endpoints/integrações:** GET /api/v1/notificacoes; GET /contador; PATCH /<id>/lida; GET/PUT /preferencias
- **Persistência/objetos:** NOTIFICACAO, NOTIFICACAO_DESTINATARIO, PREFERENCIA_NOTIFICACAO, EVENTO_NOTIFICACAO_OUTBOX
- **Frontend/mobile:** arkhe-web Dashboard notification bell/center
- **Testes existentes:** 68 testes foram reportados em sessão anterior; não reexecutados nesta produção.
- **Estado inicial:** PUBLICAÇÃO RELATADA · estrutura e rotas presentes no código.
- **Publicação/validação:** Há relato anterior de publicação, sem validação de produção nesta auditoria.
- **Ação/limite:** Sem criar evento financeiro real apenas para testar preferências.

### 12. Central de segurança e acessos

- **Solicitado:** Exibir acessos, dispositivos e operações recentes de segurança.
- **Evidência localizada:** back_arkche/conta.py · sessão/autenticação; arkhe-web/src/components/SecaoSeguranca/SecaoSeguranca.jsx; auditoria.py.
- **Endpoints/integrações:** GET /acessos; GET /sessao; POST /logout; no persistent device-session listing/revoke route found
- **Persistência/objetos:** ACESSO_CONTA and account tables; persistent session/device registry not confirmed
- **Frontend/mobile:** arkhe-web/src/components/SecaoSeguranca; device revocation UI not confirmed
- **Testes existentes:** Não foi localizado teste de revogação de dispositivo com cobertura integral nesta leitura.
- **Estado inicial:** PARCIAL · componente de segurança existe; gestão completa de dispositivos precisa validação.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não afirmar gestão de dispositivos se a tela/rota não comprovar a ação.

### 13. Status de operações

- **Solicitado:** Usar estados claros como pendente, concluída e cancelada.
- **Evidência localizada:** back_arkche/agendamentos.py; recorrencias.py; estornos.py; views de extrato e agendamentos.
- **Endpoints/integrações:** Status fields and transitions in agendamentos.py, recorrencias.py, estornos.py and cobrancas
- **Persistência/objetos:** Status columns on agendamento, recorrência, cobrança and estorno entities
- **Frontend/mobile:** arkhe-web Agendamentos, Recorrencias, Extrato and EstornosAdmin
- **Testes existentes:** Regras e testes de estados existem em módulos; não houve execução automática nesta tarefa.
- **Estado inicial:** IMPLEMENTADO POR FLUXO · nomes e transições variam conforme agendamento, recorrência ou estorno.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não generalizar uma enumeração única para todas as tabelas.

### 14. Cancelamentos e devoluções

- **Solicitado:** Cancelar pendências e permitir estorno/devolução via sistema/API conforme autorização.
- **Evidência localizada:** back_arkche/estornos.py · cancelar_cobranca/devolver_movimentacao; migrations/estornos; web/Extrato e EstornosAdmin.
- **Endpoints/integrações:** POST /api/v1/cobrancas/<id>/cancelar; POST /api/v1/movimentacoes/<id>/devolver|estornar
- **Persistência/objetos:** Estorno/cancelamento entities from migration 006; original MOVIMENTACAO retained
- **Frontend/mobile:** arkhe-web Extrato/EstornosAdmin/Boletos
- **Testes existentes:** test_estornos_regras.py cobre regras; não foi feita devolução financeira nesta produção.
- **Estado inicial:** CÓDIGO + TESTE NO REPO · devolução real continua sem validação financeira.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não mover saldo real; a API pública de devolução deve ser conferida por contrato antes da banca.

### 15. Auditoria em banco independente

- **Solicitado:** Persistir auditoria em banco separado e restringir consulta a administradores.
- **Evidência localizada:** migrations/007_auditoria_outbox_triggers.sql; back_arkche/auditoria.py; CentralAuditoria.jsx.
- **Endpoints/integrações:** GET /api/v1/admin/auditoria, /<id>, /status, /stream
- **Persistência/objetos:** AUDITORIA_EVENTO_OUTBOX in main Firebird; AUDITORIA_EVENTO in separate audit Firebird; migration 007
- **Frontend/mobile:** arkhe-web Central de Auditoria
- **Testes existentes:** test_auditoria.py existe; instalação online foi relatada, mas o fluxo trigger→banco separado não foi revalidado aqui.
- **Estado inicial:** PUBLICAÇÃO RELATADA · confirmação do evento real na central permanece pendente nesta produção.
- **Publicação/validação:** Há relato anterior de publicação, sem validação de produção nesta auditoria.
- **Ação/limite:** Captura ao vivo não realizada; não chamar evento de trigger de Pix sem prova da operação.

### 16. IA consulta e altera dados autorizados

- **Solicitado:** Permitir consultas, cadastros, edições e exclusões autorizadas pela IA.
- **Evidência localizada:** back_arkche/assistente_mauro.py; mauro_pix.py; regras financeiras usadas pelas rotas existentes.
- **Endpoints/integrações:** POST /api/v1/assistente/conversas/<id>/mensagens; generic CRUD actions are not exposed
- **Persistência/objetos:** MAURO_CONVERSA/MENSAGEM and explicitly supported bank service tables
- **Frontend/mobile:** arkhe-web MAURO chat; arbitrary CRUD actions unavailable
- **Testes existentes:** test_mauro_pix_seguro.py cobre ciclo de proposta; não comprova CRUD genérico de registros.
- **Estado inicial:** PARCIAL · consultas e Pix seguro cobertos; operações CRUD adicionais não localizadas.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não deixar o Gemini chamar SQL ou executar ferramentas bancárias livremente.

### 17. Texto e áudio em tempo real

- **Solicitado:** Conversar com o assistente por texto e áudio em tempo real.
- **Evidência localizada:** `assistente_mauro.py`; `arkhe-web/src/components/Mauro/AssistenteMauro.jsx`; `.codex-pptx-build/arkhe-app-source/src/pages/Mauro/index.jsx`.
- **Endpoints/integrações:** `/api/v1/assistente/conversas` e `/api/v1/assistente/conversas/<id>/audio/transcrever`; Flask envia áudio curto ao Gemini no backend.
- **Persistência/objetos:** histórico fica em `MAURO_CONVERSA`/`MAURO_MENSAGEM` associado à conta ativa; áudio bruto não é persistido.
- **Frontend/mobile:** web e Expo têm captura push-to-talk, transcrição e revisão do texto antes do envio; o Expo reutiliza o histórico Flask por usuário/conta.
- **Testes existentes:** 8 casos de áudio no backend; suíte completa local 130/130; web lint/build e Android bundle Expo concluídos.
- **Estado após esta tarefa:** PARCIAL · perguntas por áudio funcionam em turnos no código local; não é streaming bidirecional nem voz em tempo real.
- **Publicação/validação:** estas alterações ainda estão em branches locais/em revisão; não foram implantadas nem testadas no app publicado.
- **Ação/limite:** streaming ao vivo, respostas faladas e build nativo instalado ainda pendem. O uso de Gemini `generateContent` aqui é transcrição, não Gemini Live.

### 18. Confirmação inequívoca de operação

- **Solicitado:** Exigir confirmação explícita antes de ações financeiras ou sensíveis da IA.
- **Evidência localizada:** back_arkche/mauro_pix.py · confirmar_proposta; AssistenteMauro.jsx · botões e PIN.
- **Endpoints/integrações:** POST /api/v1/assistente/conversas/<id>/pix/propostas/<id>/confirmar; /cancelar
- **Persistência/objetos:** Pix proposal persisted by migration 009; authorization result/audit
- **Frontend/mobile:** arkhe-web MAURO proposal card with confirm/cancel
- **Testes existentes:** test_mauro_pix_seguro.py cobre expiração, escopo e estados; nenhum Pix foi autorizado nesta produção.
- **Estado inicial:** IMPLEMENTADO NO PIX · validação live segura pendente.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não enviar PIN ao Gemini ou à conversa nem executar operação durante gravação.

### 19. Histórico de conversas

- **Solicitado:** Guardar histórico de conversas e operações realizadas pelo agente.
- **Evidência localizada:** back_arkche/assistente_mauro.py · listar_conversas/listar_mensagens/enviar_mensagem; MAURO_CONVERSA/MENSAGEM.
- **Endpoints/integrações:** GET/POST /api/v1/assistente/conversas; GET/POST /api/v1/assistente/conversas/<id>/mensagens
- **Persistência/objetos:** MAURO_CONVERSA and MAURO_MENSAGEM from migration 008
- **Frontend/mobile:** arkhe-web MAURO conversation selector/history
- **Testes existentes:** Testes de intenção e proposta existem; persistência online compartilhada web/app não foi revalidada.
- **Estado inicial:** CÓDIGO LOCALIZADO · integração mobile não comprovada.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não mostrar conteúdo de conversa real de cliente no vídeo.

### 20. Contexto entre mensagens

- **Solicitado:** Manter contexto durante o atendimento.
- **Evidência localizada:** back_arkche/assistente_mauro.py · _conversa_autorizada/_detectar_intencao/enviar_mensagem.
- **Endpoints/integrações:** GET/POST /api/v1/assistente/conversas/<id>/mensagens
- **Persistência/objetos:** Conversation/message history from migration 008
- **Frontend/mobile:** arkhe-web MAURO chat history
- **Testes existentes:** test_assistente_mauro_intencoes.py cobre variações/contexto; não executado nesta produção.
- **Estado inicial:** CÓDIGO + TESTE NO REPO · continuidade ao vivo não regravada.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Cada resposta depende de consulta disponível; contexto não substitui nova autorização.

### 21. Identificar intenção

- **Solicitado:** Classificar automaticamente a intenção do usuário.
- **Evidência localizada:** back_arkche/assistente_mauro.py · _texto_normalizado/_detectar_intencao; testes de intenção.
- **Endpoints/integrações:** POST /api/v1/assistente/conversas/<id>/mensagens
- **Persistência/objetos:** Message history; intent classification runs in Python; no independent classifier table
- **Frontend/mobile:** arkhe-web MAURO chat
- **Testes existentes:** test_assistente_mauro_intencoes.py existe; conjunto do storyboard não foi reexecutado.
- **Estado inicial:** IMPLEMENTADO NO CÓDIGO · robustez total de linguagem permanece a validar.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não interpretar erro de linguagem como autorização para operar.

### 22. Defesa contra prompt injection

- **Solicitado:** Impedir que comandos maliciosos contornem autenticação ou permissões.
- **Evidência localizada:** back_arkche/assistente_mauro.py · prompt de sistema, filtro de credenciais, consulta autorizada; mauro_pix.py separado.
- **Endpoints/integrações:** POST /api/v1/assistente/conversas/<id>/mensagens; no model-supplied SQL/tools
- **Persistência/objetos:** Conversation/message history; tool allowlist is Flask code, not a separate DB policy
- **Frontend/mobile:** arkhe-web MAURO chat; deterministic backend controls
- **Testes existentes:** Testes do repo cobrem regras de intenção/proposta; suíte adversarial completa não foi localizada.
- **Estado inicial:** PARCIAL · barreiras determinísticas presentes; avaliação adversarial abrangente pendente.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Um prompt de sistema sozinho não é controle de segurança suficiente.

### 23. Permissões da IA

- **Solicitado:** Limitar ações de IA às permissões do usuário autenticado.
- **Evidência localizada:** assistente_mauro.py · _contexto_atual/_conversa_autorizada; mauro_pix.py · validar_escopo_proposta.
- **Endpoints/integrações:** MAURO conversation/message endpoints; authorization derives from backend session and account context
- **Persistência/objetos:** User/account session context and account-vinculo tables
- **Frontend/mobile:** arkhe-web MAURO session
- **Testes existentes:** test_mauro_pix_seguro.py verifica usuário/conversa/conta; autorização web não reexecutada nesta produção.
- **Estado inicial:** CÓDIGO + TESTE NO REPO · execução live não repetida.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Nunca usar privilégios de administrador para autorizar pagamento de terceiros.

### 24. Isolamento entre titulares

- **Solicitado:** Impedir que a IA consulte dados bancários de outro usuário.
- **Evidência localizada:** assistente_mauro.py · _contexto_atual/_conversa_autorizada/_dados_financeiros; mauro_pix.py · escopo.
- **Endpoints/integrações:** MAURO conversation/message endpoints; owner/vinculo is checked in Flask
- **Persistência/objetos:** User/account authorization and conversation ownership
- **Frontend/mobile:** arkhe-web MAURO session/account scope
- **Testes existentes:** test_mauro_pix_seguro.py inclui escopo de titular/conta; testes completos PF/PJ não foram executados nesta entrega.
- **Estado inicial:** IMPLEMENTAÇÃO LOCALIZADA · evidência de isolamento live pendente.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não consultar nem registrar dados de outro titular no browser real.

### 25. Modo administrativo do MAURO

- **Solicitado:** Oferecer modo administrativo do agente para administradores bancários.
- **Evidência localizada:** O MAURO atual usa escopo de cliente; admin_banco.py é módulo separado e não prova modo admin da IA.
- **Endpoints/integrações:** No administrative-mode endpoint or UI found in the initial code scan
- **Persistência/objetos:** No dedicated admin MAURO role or capability table found
- **Frontend/mobile:** No MAURO admin mode UI found
- **Testes existentes:** Não foi localizado teste/rota de agente administrativo nesta inspeção.
- **Estado inicial:** NÃO LOCALIZADO COMO MODO DO AGENTE.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não simular respostas administrativas como se fossem reais.

### 26. Consultar saldo, extrato e despesas

- **Solicitado:** Consultar saldo, extrato, despesas e movimentações autorizadas.
- **Evidência localizada:** assistente_mauro.py · _dados_financeiros/_resposta_financeira_verificada; api/get.py · saldo/movimentações/resumo.
- **Endpoints/integrações:** GET /api/v1/saldo, /api/v1/movimentacoes, /api/v1/resumo-financeiro; MAURO uses authorized financial services
- **Persistência/objetos:** CONTA, MOVIMENTACAO and linked COBRANCA/COMPRA data
- **Frontend/mobile:** arkhe-web MAURO chat
- **Testes existentes:** Consultas do MAURO podem ser conferidas contra endpoints existentes; teste com valores pessoais não foi feito nesta produção.
- **Estado inicial:** IMPLEMENTADO EM CÓDIGO · consulta real não foi repetida aqui.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não incluir saldo, extrato ou identificadores pessoais no material da banca.

### 27. Resumos financeiros

- **Solicitado:** Gerar resumos financeiros do usuário com base em movimentações reais.
- **Evidência localizada:** assistente_mauro.py · consulta de despesas e _valores_monetarios/_resposta_financeira_verificada; api/get.py · resumo-financeiro.
- **Endpoints/integrações:** GET /api/v1/resumo-financeiro and MAURO query flow; no dedicated classifier/insight endpoint found
- **Persistência/objetos:** MOVIMENTACAO and financial aggregate queries
- **Frontend/mobile:** arkhe-web Dashboard/MAURO summaries require behavior audit
- **Testes existentes:** Testes de intent exist; cálculo financeiro não foi confrontado com conjunto sintético nesta produção.
- **Estado inicial:** PARCIAL · resumos consultivos existem; análises inteligentes completas precisam prova.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não apresentar métrica ou ranking sem definir intervalo e fonte.

### 28. Categorizar despesas

- **Solicitado:** Categorizar despesas automaticamente.
- **Evidência localizada:** Na leitura realizada, não localizei pipeline dedicado de classificação automática e persistente de despesas.
- **Endpoints/integrações:** No persisted automatic expense-categorization endpoint found
- **Persistência/objetos:** No category table or movement-category link found in migrations 001–010
- **Frontend/mobile:** No expense category UI found
- **Testes existentes:** Nenhum teste dedicado de classificação foi localizado entre os testes listados.
- **Estado inicial:** NÃO LOCALIZADO COMO CLASSIFICADOR AUTOMÁTICO.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não fabricar uma categoria ou afirmar que o requisito está concluído.

### 29. Alertas financeiros inteligentes

- **Solicitado:** Alertar gastos incomuns, saldo baixo e movimentações suspeitas.
- **Evidência localizada:** notificacoes.py fornece persistência e categorias; não foi localizado motor completo de anomalia em despesas.
- **Endpoints/integrações:** Notification API and worker exist; no complete rule-engine endpoint for smart alerts found
- **Persistência/objetos:** Notification storage exists; rule/evaluation history for smart insights not found
- **Frontend/mobile:** Notification center exists; intelligent rule settings not found
- **Testes existentes:** test_notificacoes_isoladas.py testa outbox/preferência, não a qualidade de um detector financeiro.
- **Estado inicial:** PARCIAL · central de avisos existe; inteligência de alerta não está comprovada.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não chamar alerta estático de detecção de comportamento anômalo.

### 30. Bloquear operações suspeitas

- **Solicitado:** Detectar movimentação suspeita e bloquear operações/cartões até confirmação.
- **Evidência localizada:** A inspeção não encontrou motor de detecção com bloqueio automático de movimento/cartão.
- **Endpoints/integrações:** POST /api/v1/vendas/cartao; POST /maquininha/comprar; dormant /adicionar_compra route is not imported by main.py
- **Persistência/objetos:** COMPRA, MOVIMENTACAO.ID_COMPRA (migration 010), IDEMPOTENCIA_VENDA (migration 011 aditiva; ainda não aplicada na produção)
- **Frontend/mobile:** arkhe-web/src/components/Maquininha/ArkhePay.jsx and useMaquininha.js; external API docs/example
- **Testes existentes:** 41 testes de integração de vendas executados em Firebird temporário; cobrem replay, duas compras iguais com chaves distintas, mudança de payload, concorrência, rollback, relacionamento e contabilidade COMPRA/MOVIMENTACAO.
- **Estado inicial:** O código rejeitava vendas parecidas em cinco minutos, não identificava a mesma solicitação; no endpoint de API a junção não usava `M.ID_COMPRA = C.ID_COMPRA`. A maquininha tinha heurística separada para débito. Nenhuma delas provava fraude nem bloqueava cartão/conta.
- **Correção local:** API, maquininha e rota legado usam agora chave persistida em `IDEMPOTENCIA_VENDA`, gravada no mesmo commit da COMPRA/MOVIMENTACAO; a mesma chave e parâmetros devolvem a resposta anterior; mesma chave com parâmetros diferentes retorna 409; chaves distintas permitem compras legítimas iguais. Nenhum valor ou cartão real foi usado.
- **Resultado real:** 41/41 testes do módulo `tests/test_api_vendas.py` e 116/116 testes da suíte backend passaram com Firebird isolado local. A contabilidade para API de crédito permaneceu ligada por `MOVIMENTACAO.ID_COMPRA`; não foi alterada a semântica já existente da maquininha, cujo crédito registra COMPRA/FATURA sem movimento de liquidação.
- **Publicação/validação:** Correção enviada à branch `codex/main-sprint-p0-idempotency` (`262b696`); não foi mesclada à `main` nem implantada. A migration 011 depende de backup Firebird online validado antes de aplicar.
- **Pendência:** Detecção explicável de risco e fluxo de bloqueio/revisão/desbloqueio continuam ausentes. Idempotência evita replay técnico; não substitui antifraude nem satisfaz sozinho o requisito de bloqueio até confirmação.

### 31. PIN para ação sensível

- **Solicitado:** Exigir PIN, senha ou código para operações sensíveis feitas pela IA.
- **Evidência localizada:** mauro_pix.py · confirmar_proposta/verificação do PIN/tentativas; AssistenteMauro.jsx · formulário protegido.
- **Endpoints/integrações:** POST /api/v1/assistente/conversas/<id>/pix/propostas/<id>/confirmar
- **Persistência/objetos:** PIN verification against existing user PIN; proposal table from migration 009
- **Frontend/mobile:** arkhe-web MAURO PIN dialog during Pix confirmation
- **Testes existentes:** test_mauro_pix_seguro.py testa transições; não foram feitas tentativas reais de PIN nesta produção.
- **Estado inicial:** IMPLEMENTADO NO PIX · outros tipos de ação sensível não habilitados pelo assistente.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não registrar ou capturar PIN, senha, CVV ou token.

### 32. Tratar comandos inválidos

- **Solicitado:** Dar tratamento claro a comandos inválidos ou incompletos enviados à IA.
- **Evidência localizada:** assistente_mauro.py · respostas de erro/fallback; Mauro Pix trata estados e respostas de validação.
- **Endpoints/integrações:** POST /api/v1/assistente/conversas/<id>/mensagens
- **Persistência/objetos:** Conversation/message rows; errors in Flask responses
- **Frontend/mobile:** arkhe-web MAURO chat
- **Testes existentes:** test_assistente_mauro_intencoes.py e test_mauro_pix_seguro.py; não executados nesta produção.
- **Estado inicial:** CÓDIGO LOCALIZADO · experiência ponta a ponta não revalidada.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Nunca trocar erro técnico por saldo zero ou lista vazia.

### 33. Sugerir opções quando não entende

- **Solicitado:** Oferecer caminhos quando não entender a solicitação.
- **Evidência localizada:** assistente_mauro.py · _detectar_intencao/_resposta_pedido_financeiro; AssistenteMauro.jsx · sugestões.
- **Endpoints/integrações:** POST /api/v1/assistente/conversas/<id>/mensagens
- **Persistência/objetos:** Conversation/message rows; assistant fallback text
- **Frontend/mobile:** arkhe-web MAURO chat fallback
- **Testes existentes:** Testes de intenção existem; variedade de ambiguidades e erros de português não foi reexecutada.
- **Estado inicial:** PARCIAL · fallback e perguntas de esclarecimento existem; cobertura linguística precisa demonstração.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Sugestões não devem autorizar execução financeira.

### 34. Notificações pelo WhatsApp

- **Solicitado:** Enviar notificações aos clientes pelo WhatsApp.
- **Evidência localizada:** back_arkche/api/whatsapp.py; docs/WHATSAPP_AUTORIZACAO.md; n8n/WAHA externos ao checkout inspecionado.
- **Endpoints/integrações:** WAHA/n8n external workflow cannot be confirmed from the checked-out repositories
- **Persistência/objetos:** External n8n/WAHA data store not included in these repositories
- **Frontend/mobile:** External WhatsApp client via n8n/WAHA, not in code checkout
- **Testes existentes:** test_whatsapp_vinculos.py cobre parte do vínculo; envio live não foi realizado.
- **Estado inicial:** PARCIAL / EXTERNO · código de integração presente; entrega de notificação não validada aqui.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** O usuário solicitou preservar MAURO/WAHA/n8n; nenhuma alteração foi feita.

### 35. Consultar saldo e extrato no WhatsApp

- **Solicitado:** Permitir consulta de saldo e extrato pelo WhatsApp.
- **Evidência localizada:** api/whatsapp.py · vínculo/nível; api/common.py · autenticar_requisicao; api/post.py · whatsapp_consulta.
- **Endpoints/integrações:** POST /internal/whatsapp/consulta (internal service route)
- **Persistência/objetos:** WhatsApp link/configuration records and normal account/movement tables
- **Frontend/mobile:** External WhatsApp client; not exercised online here
- **Testes existentes:** test_whatsapp_vinculos.py existe; não houve consulta live nesta produção.
- **Estado inicial:** CÓDIGO LOCALIZADO · integração online não revalidada nesta tarefa.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não publicar respostas ou números de uma conta real.

### 36. Pagamentos pelo WhatsApp

- **Solicitado:** Permitir pagamentos e transferências pelo WhatsApp.
- **Evidência localizada:** api/post.py · pagamento Pix/boletos; api/common.py · limitar_pagamento_whatsapp/autorizar_pagamento_externo.
- **Endpoints/integrações:** POST /api/v1/pagamentos/pix; POST /api/v1/pagamentos/dda/<id>; WhatsApp authorization path must be validated externally
- **Persistência/objetos:** COBRANCA and MOVIMENTACAO; transaction services
- **Frontend/mobile:** External WhatsApp/n8n operation UI, not in code checkout
- **Testes existentes:** test_api_pagamentos_isolados.py e test_whatsapp_vinculos.py existem; nenhum pagamento real foi feito.
- **Estado inicial:** IMPLEMENTADO EM CÓDIGO · caminho publicado não foi exercitado nesta produção.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Teto de WhatsApp não se estende automaticamente a web ou API.

### 37. Autenticação adicional no WhatsApp

- **Solicitado:** Exigir autenticação adicional nas operações do WhatsApp.
- **Evidência localizada:** api/whatsapp.py · verificar_nivel_whatsapp; api/common.py · autenticar_requisicao; endpoints internos.
- **Endpoints/integrações:** POST /internal/whatsapp/confirmar; permission is checked from the backend-linked account
- **Persistência/objetos:** WhatsApp link/permission records; no credential in chatbot prompt
- **Frontend/mobile:** External WhatsApp/n8n authentication flow
- **Testes existentes:** test_whatsapp_vinculos.py cobre níveis e vínculo; não testado contra serviço live nesta produção.
- **Estado inicial:** CÓDIGO + TESTE NO REPO · configuração online pendente de revalidação.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não confundir autenticação adicional com confirmação do modelo de IA.

### 38. Notificações em tempo real

- **Solicitado:** Notificar movimentações e acessos em tempo real, mantendo histórico após reinício.
- **Evidência localizada:** notificacoes.py · EVENTO_NOTIFICACAO_OUTBOX/processar_outbox_pendente; notificacoes API; dashboard sino.
- **Endpoints/integrações:** Notification routes /api/v1/notificacoes* and outbox/Redis worker; user-facing live delivery not revalidated
- **Persistência/objetos:** Persistent notifications and outbox in migration 001; Redis as transport
- **Frontend/mobile:** arkhe-web Dashboard notification center; no Expo push validation
- **Testes existentes:** test_notificacoes_isoladas.py inclui Redis indisponível/duplicidade; 68 testes foram reportados antes, não reexecutados aqui.
- **Estado inicial:** IMPLEMENTADO EM CÓDIGO · entrega live não revalidada nesta apresentação.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não afirmar push mobile; entrega mobile fechada é etapa futura.

### 39. API de pagamentos fictícios

- **Solicitado:** Expor APIs para cartão, débito e boleto fictício.
- **Evidência localizada:** back_arkche/api/get.py; api/post.py; api/common.py; tests/test_api_vendas.py.
- **Endpoints/integrações:** GET /api/v1/*; POST /api/v1/cobrancas/* and /api/v1/vendas/cartao
- **Persistência/objetos:** INTEGRACAO_API plus normal COBRANCA, COMPRA, FATURA_COMPRA, MOVIMENTACAO tables
- **Frontend/mobile:** arkhe-web/src/pages/ApiDocs/ApiDocs.jsx and API integration examples
- **Testes existentes:** test_api_vendas.py e test_api_pagamentos_isolados.py existem; build da API não reexecutado aqui.
- **Estado inicial:** IMPLEMENTAÇÃO PARCIALMENTE COBERTA · catálogo de endpoints não foi testado em publicação.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não apresentar endpoint de teste como integração com bandeira ou rede financeira real.

### 40. Documentação da API pública

- **Solicitado:** Documentar a API pública com contratos, autenticação, erros e exemplos.
- **Evidência localizada:** back_arkche/docs/ARQUITETURA_API.md; rotas em back_arkche/api/get.py e post.py.
- **Endpoints/integrações:** Frontend route/page /dashboard/api-docs; docs/ARQUITETURA_API.md; Postman collection
- **Persistência/objetos:** Versioned docs, examples and Postman JSON; no OpenAPI spec confirmed
- **Frontend/mobile:** arkhe-web/src/pages/ApiDocs/ApiDocs.jsx
- **Testes existentes:** Documentação localizada; validação automatizada entre OpenAPI/contrato e código não localizada.
- **Estado inicial:** PARCIAL · documentação existente, completude do contrato público não comprovada.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não afirmar documentação completa sem inventário/versionamento validado.

### 41. Rate limiting

- **Solicitado:** Limitar requisições das APIs para reduzir abuso e sobrecarga.
- **Evidência localizada:** api/common.py agora aplica cota Redis compartilhada após autenticação de credenciais da integração, sem tocar nas rotas WhatsApp.
- **Endpoints/integrações:** Rotas `/api/v1/...` autenticadas por `X-Client-ID` e `X-Client-Secret`; parâmetros `ARKHE_API_RATE_LIMIT` e `ARKHE_API_RATE_WINDOW_SECONDS`.
- **Persistência/objetos:** Redis `INCR` + `EXPIRE` atômicos por ID de integração; `429` com `Retry-After`; falha fechada `503` se Redis estiver indisponível.
- **Frontend/mobile:** arkhe-web integration page; no central limiter dashboard found
- **Testes existentes:** `tests/test_api_rate_limiting.py` tem 6 casos incluindo integração com a autenticação real: 429, janelas, isolamento entre integrações, Redis offline, configuração inválida e bypass somente em TESTING.
- **Estado após esta tarefa:** IMPLEMENTADO LOCALMENTE E TESTADO; limite default 120/minuto por integração; WhatsApp, rotas internas e sessões de usuário não são alterados por este controle.
- **Publicação/validação:** Enviada à branch `codex/main-sprint-p0-idempotency` (`a5a78d3`); não mesclada nem implantada. Requer release backend e `REDIS_URL`; sem migration própria.
- **Ação/limite:** Não bombardear serviços publicados para demonstrar rate limiting.

### 42. Painel de integrações

- **Solicitado:** Gerenciar integrações e credenciais da API em interface própria.
- **Evidência localizada:** api/get.py/api/post.py · /integracoes/api; arkhe-web/src/pages/Integracoes/Integracoes.jsx.
- **Endpoints/integrações:** GET/POST /integracoes/api and /integracoes/api/<id>/regenerar-secret
- **Persistência/objetos:** INTEGRACAO_API and hashed secret fields
- **Frontend/mobile:** arkhe-web/src/pages/Integracoes/Integracoes.jsx
- **Testes existentes:** Não foi feita alteração de credencial ou teste de rotação nesta produção.
- **Estado inicial:** CÓDIGO + TELA EXISTE · teste live de gerenciamento não realizado.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não incluir CLIENT_SECRET, token ou valor de variável no vídeo/deck.

### 43. Sessões e dispositivos

- **Solicitado:** Gerenciar sessões e dispositivos conectados.
- **Evidência localizada:** conta.py fornece autenticação/sessão; SecaoSeguranca.jsx aparece na UI; gestão por dispositivo não foi comprovada.
- **Endpoints/integrações:** GET /sessao; POST /logout; /acessos* handles delegated account access, not necessarily device sessions
- **Persistência/objetos:** JWT/session cookie and ACESSO_CONTA; no durable device-session registry found
- **Frontend/mobile:** arkhe-web security section; no device/session list or revoke control confirmed
- **Testes existentes:** Não foi localizado teste de revogação por dispositivo nesta inspeção.
- **Estado inicial:** PARCIAL · login/sessão existe; gestão e revogação de dispositivos pendem validação.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não encerrar ou alterar sessões de clientes reais.

### 44. Integrar agentes externos por REST

- **Solicitado:** Permitir agentes externos consumirem funcionalidades bancárias via REST.
- **Evidência localizada:** back_arkche/api/common.py; endpoints /api/v1; `arkhe-mcp/` é repositório separado com cliente HTTP, não prova uso no fluxo principal.
- **Endpoints/integrações:** Authenticated REST integration routes in api/get.py and api/post.py; no MCP server used
- **Persistência/objetos:** Existing REST bank entities and INTEGRACAO_API
- **Frontend/mobile:** External REST clients; no MCP
- **Testes existentes:** Não foi realizada chamada de agente externo live nesta tarefa.
- **Estado inicial:** REST DISPONÍVEL EM CÓDIGO · integração de agente não validada em produção.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** A existência de `arkhe-mcp` não deve ser apresentada como deploy principal da sprint.

### 45. Autenticar e autorizar agentes

- **Solicitado:** Autenticar agentes externos e limitar suas permissões.
- **Evidência localizada:** api/common.py · autenticar_integracao/autenticar_requisicao; escopo em API e WhatsApp.
- **Endpoints/integrações:** X-Client-ID/X-Client-Secret auth and WhatsApp linked-account level checks in api/common.py
- **Persistência/objetos:** INTEGRACAO_API credentials, linked account and WhatsApp permission level
- **Frontend/mobile:** Integration setup UI and WhatsApp link controls
- **Testes existentes:** test_api_pagamentos_isolados.py e test_whatsapp_vinculos.py cobrem casos relacionados; teste abrangente de agentes pendente.
- **Estado inicial:** IMPLEMENTADO EM PARTE · controle de integração existe; escopo de todos os agentes precisa validação.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não usar ou exibir segredo real.

### 46. Ferramentas REST de leitura

- **Solicitado:** Oferecer consultas de saldo, extrato e movimentações por APIs autorizadas.
- **Evidência localizada:** api/get.py · /api/v1/saldo, /movimentacoes, /resumo-financeiro, cobranças e cartão.
- **Endpoints/integrações:** GET /api/v1/conta, /saldo, /movimentacoes, /resumo-financeiro
- **Persistência/objetos:** CONTA and MOVIMENTACAO; COBRANCA/DDA views
- **Frontend/mobile:** arkhe-web dashboard/extract uses current Flask services
- **Testes existentes:** Existem testes de API de pagamentos/leitura; consumo por agente externo não foi repetido.
- **Estado inicial:** ROTAS LOCALIZADAS · validação por credencial externa live pendente.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Nenhum dado real de conta entra no vídeo.

### 47. Ferramentas REST de escrita

- **Solicitado:** Oferecer pagamentos, transferências e cadastros pelas APIs autorizadas.
- **Evidência localizada:** api/post.py · cobrança Pix/boleto, pagamento Pix/boletos, vendas fictícias; api/common.py · idempotência.
- **Endpoints/integrações:** POST /api/v1/pagamentos/pix, /pagamentos/dda/<id>, /cobrancas/* and /vendas/cartao
- **Persistência/objetos:** COBRANCA and MOVIMENTACAO; idempotency for external payment paths differs by channel
- **Frontend/mobile:** web payments use existing financial flows; API write calls documented
- **Testes existentes:** test_api_pagamentos_isolados.py/test_api_vendas.py existem; nenhuma escrita real ocorreu nesta produção.
- **Estado inicial:** CÓDIGO LOCALIZADO · operação de escrita live não demonstrada.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não considerar POST HTTP 200 como prova de persistência financeira correta.

### 48. Documentar ferramentas de agente

- **Solicitado:** Documentar contratos REST destinados a agentes externos.
- **Evidência localizada:** back_arkche/docs/ARQUITETURA_API.md e endpoints internos; documentação de ferramentas completa não foi comprovada.
- **Endpoints/integrações:** docs/ARQUITETURA_API.md, docs/WHATSAPP_AUTORIZACAO.md, web ApiDocs and examples
- **Persistência/objetos:** Markdown/API page/example files; no formal OpenAPI contract confirmed
- **Frontend/mobile:** web API docs page, markdown docs and sample code
- **Testes existentes:** Não há validação automatizada de contrato documental localizada.
- **Estado inicial:** PARCIAL · docs gerais existem; guia completo do agente deve ser conferido.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não inventar rota, schema ou capacidade externa.

### 49. Gerenciar cartões fictícios

- **Solicitado:** Criar e gerenciar cartões acadêmicos/fictícios com controles de segurança.
- **Evidência localizada:** back_arkche/cartao.py; arkhe-web/src/components/Cartao/CartaoResumo.jsx e ModalCartao.jsx.
- **Endpoints/integrações:** GET /cartao, /cartao/compras, /cartao/faturas; POST /adicionar_cartao; PUT /bloquear_cartao
- **Persistência/objetos:** CARTAO, COMPRA, FATURA_COMPRA; migration 010 split card credit from operational limits
- **Frontend/mobile:** arkhe-web card/dashboard and transaction pages
- **Testes existentes:** test_api_vendas.py cobre vendas/cartão; cadastro e fatura não foram retestados nesta produção.
- **Estado inicial:** IMPLEMENTADO EM CÓDIGO · teste de ponta a ponta não feito nesta apresentação.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Nunca exibir PAN completo, CVV ou cartão de cliente.

### 50. Cartão virtual

- **Solicitado:** Permitir criação de cartão virtual fictício.
- **Evidência localizada:** cartao.py cria/serializa cartões; a versão inspecionada não comprovou, por si só, tipo virtual persistido.
- **Endpoints/integrações:** CARTAO persists card records; no separate virtual-card creation endpoint/type was confirmed
- **Persistência/objetos:** CARTAO table; virtual/card type distinction still unconfirmed
- **Frontend/mobile:** Card UI exists; genuine persisted virtual-card type not proven
- **Testes existentes:** Não foi localizado teste dedicado de criação de cartão virtual nesta inspeção.
- **Estado inicial:** PARCIAL / PERSISTÊNCIA VIRTUAL A CONFIRMAR.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não confundir uma ilustração de cartão com cartão virtual funcional.

### 51. Bloqueio após erros de login

- **Solicitado:** Bloquear temporariamente conta após várias tentativas incorretas.
- **Evidência localizada:** back_arkche/conta.py · registrar_falha_login/login_temporariamente_bloqueado; tests/test_login_bloqueio.py.
- **Endpoints/integrações:** POST /login_usuario and /login; temporary lock is in conta.py
- **Persistência/objetos:** Redis login counters/block TTL and user/session records
- **Frontend/mobile:** Login UI receives backend lockout response
- **Testes existentes:** Teste isolado existe e o bloqueio foi preservado no histórico; não foi reexecutado agora.
- **Estado inicial:** IMPLEMENTADO EM CÓDIGO + TESTE NO REPO.
- **Publicação/validação:** Publicação não revalidada nesta tarefa; código local não é prova de deploy.
- **Ação/limite:** Não tentar bloquear conta real durante a apresentação.

### 52. IA fora do WhatsApp

- **Solicitado:** Disponibilizar a inteligência artificial fora do canal WhatsApp.
- **Evidência localizada:** `assistente_mauro.py`, `mauro_pix.py`, `arkhe-web/src/components/Mauro/AssistenteMauro.jsx` e `.codex-pptx-build/arkhe-app-source/src/pages/Mauro/index.jsx`.
- **Endpoints/integrações:** Web e Expo usam as rotas Flask de conversa; autenticação, conversa e histórico respeitam a conta selecionada no backend.
- **Persistência/objetos:** `MAURO_CONVERSA`/`MAURO_MENSAGEM`; Gemini chamado pelo servidor e credencial não enviada ao cliente.
- **Frontend/mobile:** web inclui fluxo de Pix com proposta/PIN; Expo agora tem chat textual e áudio transcrito, mas não expõe autorização/execução de proposta Pix.
- **Testes existentes:** suíte backend local 130/130; lint/build web e bundle Android Expo passaram; não houve pergunta ao Gemini real nesta execução.
- **Estado após esta tarefa:** PARCIAL · assistência web existente e tela móvel adicionada localmente; uso mobile ainda não publicado, nem validado contra sessão real.
- **Publicação/validação:** web, backend e Expo nesta etapa não foram implantados. PRs atuais seguem rascunho; migration de idempotência pendente.
- **Ação/limite:** não afirmar IA 52/52 ou MAURO mobile em produção; falta publicar/instalar o app e fechar o fluxo mobile de confirmação financeira.

## Checkpoint de implementação

1. P0: idempotência persistente por chave para API, maquininha e rota de compra legado foi implementada localmente e coberta por Firebird isolado. A migration 011 ainda precisa de backup validado antes da produção. Isto não substitui o motor de risco/bloqueio requerido no item 30.
2. Próximos grupos por ordem: autorização/sessões e isolamento; classificação e alertas; cartão virtual; modo administrativo e ações do MAURO; completar voz em tempo real; n8n; regressão e validação externa.
3. Não publicar uma migração em produção sem backup recém-criado e validado. Não executar operações que alterem saldos nem bloquear titulares reais.
4. Estado atual: matriz criada; não afirmar 52/52. Este é um progresso de branches; não foi implantado no Arkhé.

## Checkpoint de implementação — 2026-10-26

- **Backend:** branch `codex/main-sprint-p0-idempotency`; commits `262b696` e `a5a78d3`; [PR #5](https://github.com/GPontin78/back_arkche/pull/5), aberto como rascunho. Suíte completa local: 122/122 testes com Firebird temporário.
- **Frontend:** branch `codex/main-sprint-client-idempotency`; commit `8fcdc94`; [PR #2](https://github.com/LucasGajardoni/arkhe-web/pull/2), aberto como rascunho. `npm run lint` e `npm run build` passaram; `node tests/maquininha.mjs` não iniciou por ausência do pacote Playwright neste workspace.
- **Produção:** nenhuma migration ou operação financeira foi executada no Firebird online. Migration 011 precisa de backup recente, restauração/validação do arquivo de backup e aplicação na base principal antes da versão backend dependente da tabela. Nenhum deploy foi realizado.
- **Navegador:** a inspeção solicitada pelo fluxo de validação não avançou: o controle do Chrome encerrou a automação porque não conseguiu determinar com confiança a URL da janela ativa. Não foi inferida autenticação nem testada a aplicação publicada.
- **Próxima continuidade:** tratar, com módulos e checkpoints separados, risco/fraude com critérios justificáveis, classificação e alertas financeiros, sessões/dispositivos, cartão virtual persistido, modo administrativo do MAURO, voz web/Expo e validação real das integrações externas. A inspeção do n8n/WAHA depende de acesso ao workflow e não deve alterar o MAURO do WhatsApp.
- **Classificação geral:** a matriz de 52 itens é uma auditoria inicial com progresso parcial; não certifica publicação nem 52/52 concluídos.

## Checkpoint incremental — MAURO com áudio por turnos — 2026-10-26

- **Backend:** `assistente_mauro.py` adiciona transcrição autenticada, valida conversa/conta ativa, aceita somente áudio permitido de até 2 MB, limita o uso e envia o áudio ao Gemini somente no servidor. Não persiste áudio bruto nem transcrição até o usuário revisar e enviar. A rota registra somente metadados de auditoria. Oito testes específicos e suíte completa 130/130 passaram com Firebird temporário.
- **Web:** gravação limitada a 30 segundos, envio ao Flask e prévia editável; lint e build passaram.
- **Expo:** nova tela MAURO compartilha conversas Flask do usuário/conta ativa, tem gravação curta via `expo-audio`, revisão antes de enviar e atalho na dashboard. Android export compilou. A instalação nativa requer build/instalação do app e permissão de microfone em runtime.
- **Limite funcional:** trata-se de fala para texto em turnos, sem áudio de resposta, streaming duplex nem Gemini Live. O requisito 17 continua parcial.
- **Branches:** áudio backend/web foi acrescentado às PRs já abertas; a implementação Expo está local na branch `codex/main-sprint-mauro-mobile-audio`. Nenhuma PR desta etapa foi mesclada nem implantada.
- **Ambiente externo:** Chrome/EasyPanel não foram acessados nesta execução; o controle do Chrome já havia encerrado por não determinar a URL ativa com confiança. Não se validou Gemini online, sessão real, Firebird online ou deploy.
- **Reinstalação Expo:** `npm ci --legacy-peer-deps --no-audit --no-fund` concluiu; `expo export --platform android` passou. A instalação inicial padrão foi bloqueada por conflito de peer dependency React/React DOM no lockfile; o uso de `legacy-peer-deps` apenas manteve as versões travadas e permitiu validar o bundle.
