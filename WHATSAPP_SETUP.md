# WhatsApp Arkhé — preparação e implantação (nível 1)

O código está em branch de desenvolvimento, NÃO foi testado ou implantado no EasyPanel. O workflow inicial responde a comandos, não possui agente de IA, não movimenta dinheiro e não deve ser usado com clientes reais antes dos testes.

## Arquitetura e autenticação

WAHA (sessão arkhe, GOWS) → webhook n8n com autenticação por header → backend → MCP → banco Firebird. O resultado volta ao n8n e é enviado pelo WAHA.

O cliente entra no site Arkhé, seleciona a conta PF ou PJ, abre a página WhatsApp no dashboard e habilita nível 1. O site gera um código temporário de 8 dígitos, válido por 10 minutos e com 5 tentativas. O cliente envia esse código por conversa privada com o WhatsApp do Arkhé. Só depois o backend cria a sessão da conta selecionada por 30 minutos. A cada consulta o n8n recebe do backend um token MCP de curta duração. Nunca colocar o token no prompt da IA ou na mensagem do cliente. O comando **sair** invalida a sessão.

## Matriz de permissões

| Perfil | Consultas financeiras | Funcionários e folha |
|---|---|---|
| Titular PF | Sim | Não |
| Proprietário PJ | Sim | Sim |
| PJ Administrativo (0), Financeiro (1), Contador (2) | Sim | Não |
| PJ RH (3) | Não | Sim |
| PJ Compras (4), Outro (5) | Não | Não |

Acesso de colaboradores PJ deve estar ativo em ACESSO_CONTA. As permissões são revalidadas em toda consulta MCP. Desativar o WhatsApp invalida código e sessão para a conta. Níveis 2 e 3 indisponíveis.

## Implantação

1. **Faça backup do Firebird de produção** antes de executar manualmente migrations/20261019_whatsapp_config.sql uma única vez. Essa migração cria WHATSAPP_CONFIG e WHATSAPP_SESSAO sem alterar o esquema das tabelas antigas. Sem executar a migração, as rotas de WhatsApp não funcionarão.
2. No backend EasyPanel, definir N8N_SERVICE_KEY com segredo forte exclusivo, preservar SECRET_KEY e MCP_SERVICE_KEY atuais e conferir FRONTEND_URL com a origem exata do frontend.
3. No n8n, definir ARKHE_BACKEND_URL com a URL base do backend (sem barra final), importar workflows/arkhe_whatsapp_nivel1_n8n.json e conferir se a versão instalada autoriza usar $env.ARKHE_BACKEND_URL em expressões. Caso não, substituir cada expressão URL do backend por sua URL completa real.
4. No n8n, criar credenciais do tipo Header Auth e selecioná-las NOS NÓS de requisição: Validar código, Encerrar sessão e Obter sessão MCP usam X-Arkhe-N8N-Key com N8N_SERVICE_KEY; Consultar MCP usa X-Arkhe-Client-Key com ARKHE_MCP_CLIENT_KEY; Enviar WhatsApp usa X-Api-Key com WAHA_API_KEY.
5. No webhook Receber WAHA no n8n, criar credencial Header Auth, exemplo X-Arkhe-Webhook-Key e um segredo aleatório exclusivo. Esse header é OBRIGATÓRIO: sem autenticar o emissor, qualquer um poderia simular o telefone de um cliente autenticado.
6. No WAHA, configurar o evento **message** com a URL de PRODUÇÃO do webhook n8n e customHeaders correspondente a X-Arkhe-Webhook-Key. O WAHA permite isso por sessão ou globalmente por WHATSAPP_HOOK_CUSTOM_HEADERS=X-Arkhe-Webhook-Key:SEU_SEGREDO; WHATSAPP_HOOK_URL e WHATSAPP_HOOK_EVENTS=message. Não duplicar webhooks de sessão e globais.
7. Confirmar no WAHA sessão arkhe = WORKING, não apenas STARTING/SCAN_QR_CODE/FAILED. Ativar o workflow no n8n somente após configurar credenciais. Não colocar segredos em parâmetros, Git, mensagens ou capturas de tela.
8. Confirmar que o n8n NÃO salva dados de execuções de sucesso ou falha contendo códigos de acesso ou tokens, nem expõe as credenciais no histórico.

## Endpoints

Site autenticado por cookie de conta:
- GET /whatsapp/configuracao
- PUT /whatsapp/configuracao com corpo {"nivel":0} ou {"nivel":1} (valida Origin)
- POST /whatsapp/codigo (valida Origin)

Serviço interno autenticado com X-Arkhe-N8N-Key:
- POST /internal/whatsapp/iniciar com {"telefone":"55..."}; não revela existência de cliente, dados bancários ou contas.
- POST /internal/whatsapp/selecionar-conta com {"telefone":"55...","codigo":"12345678"}. A seleção ocorre na conta ativa no site, não por uma opção digitada na conversa.
- POST /internal/whatsapp/sessao com {"telefone":"55..."}; retorna token MCP temporário.
- POST /internal/whatsapp/encerrar com {"telefone":"55..."}.

## Verificações mínimas antes de mesclar

- Executar: python -m unittest discover -s tests -p test_whatsapp_permissoes.py
- Conferir isolamento entre PF e PJ, cliente titular e colaborador, cargos RH/financeiro.
- Tentar 5 códigos errados, código expirado, reutilizado, telefone diferente, alteração de conta e revogação de acesso.
- Confirmar que o MCP recusa sessão desativada, vencida ou de outra conta.
- Conferir n8n → MCP com headers dinâmicos, status HTTP e saída JSON-RPC da versão instalada.
- Testar os comandos saldo, extrato, dda, boletos, faturas, limites, chaves pix, funcionarios, folhas e sair em WhatsApp privado.
- Verificar que não responde mensagens próprias, grupos ou mídia e que o webhook autentica o remetente.

Referências: https://waha.devlike.pro/docs/how-to/events/ e https://waha.devlike.pro/docs/how-to/config/

Aviso: o WAHA é mecanismo não oficial de WhatsApp e o pareamento pode sofrer restrições. Para atendimento bancário real, avaliar a API oficial WhatsApp Business e políticas de privacidade antes de produção.
