# Log direto no Firebird separado

As triggers usam `TG_AI_<TABELA>_LOG`, `TG_AU_<TABELA>_LOG` e
`TG_AD_<TABELA>_LOG`, conforme inclusão, alteração e exclusão.
São 105 triggers nas 35 tabelas de negócio. Cada uma lê a configuração e executa
um `INSERT` parametrizado em `AUDITORIA_EVENTO` com `EXECUTE STATEMENT ... ON
EXTERNAL DATA SOURCE ... WITH COMMON TRANSACTION`. Não há procedure geral de log.
As duas triggers financeiras mantêm suas regras e posições.

Mensagens, conversas, propostas Pix, tentativas de PIN e consultas HTTP do MAURO
entram na auditoria. Eventos sem alteração de tabela, como consultas e recusas,
são registrados pelo Python. O sucesso das mensagens e confirmações Pix é
auditado antes do commit, na mesma transação da ação.

O log inclui usuário, conta, rota, horário, valor e snapshots de metadados. Não
copia mensagens privadas, áudio, PIN, CVV, senhas, tokens, hashes, documentos ou
chaves Pix. Os IDs das mensagens permitem relacionar o log ao histórico já salvo.

`CONFIGURACAO_LOG` guarda um único destino: datasource, usuário, senha e origem.
O aplicador preenche os valores usando as variáveis `ARKHE_AUDIT_DB_*` já
configuradas, por parâmetros. Não publicar os valores dessa tabela nem conceder
SELECT a usuários de negócio. As próprias triggers recebem SELECT e USAGE na
sequência, sem abrir acesso direto às credenciais. Isso atende também conexões do
MCP e do DBeaver, sem depender de contexto de conexão configurado pelo backend.
`ARKHE_AUDIT_DATA_SOURCE` permite usar um endereço específico acessível a partir
do servidor Firebird; na ausência dele, usa host/porta/nome das variáveis atuais.

## Publicação

1. Publicar o backend atualizado. Antes da migração ele continua compatível com
   a outbox antiga e normaliza CREATE/EXECUTE para INSERT/UPDATE.
2. No backend, executar `python scripts/aplicar_log_externo.py`. Essa conferência
   é somente leitura e recusa mudanças de schema/triggers desde o estudo.
3. Executar `python scripts/aplicar_log_externo.py --apply`. O aplicador faz
   backups Firebird dos dois bancos e salva o rollback do DDL em `.runtime/`.
4. A estrutura auxiliar é criada primeiro. A configuração, as novas triggers e
   a retirada das antigas são confirmadas juntas após uma leitura EDS de teste.
   Falha nessa etapa reverte a troca e remove a estrutura auxiliar criada.
5. Conferir a Central de Auditoria e o catálogo, sem operações financeiras de QA
   no banco real. As bases antigas e os eventos já registrados são preservados.

Os eventos anteriores que ainda estiverem na outbox continuam sendo entregues
pelo worker existente. A nova origem termina em `-log-v2`, evitando colisão com
os IDs antigos. A API administrativa usa a chave `ID_AUDITORIA` do arquivo, que é
única entre origens. O Redis sinaliza mudanças para o feed; a consulta periódica
continua disponível.

Não executar o SQL da migração isoladamente: o aplicador precisa inserir a
configuração por parâmetros antes de ativar a troca.

## Transações e validação

Uma falha na gravação externa é propagada à operação, conforme a decisão de usar
gravação direta obrigatória. Não existe nova fila de contingência. Rollbacks
normais removem tanto a operação quanto o log externo.

O EDS não oferece commit em duas fases. `WITH COMMON TRANSACTION` acompanha o
commit/rollback da transação principal, mas não garante atomicidade distribuída
em uma falha do servidor durante o commit. Referência:
[Firebird, EXECUTE STATEMENT](https://www.firebirdsql.org/refdocs/langrefupd25-psql-execstat.html).

`python -m unittest tests.test_log_externo_firebird -v` cria dois bancos novos
com dados fictícios, testa as 105 operações de trigger, antes/depois, JSON,
rollback, configuração, falha externa, aliases CREATE/EXECUTE, parcelas e o
fluxo HTTP da IA com resposta simulada. As colunas da fixture foram extraídas do
catálogo online em 26/10/2026; ela não reproduz todos os índices e FKs.

Para testar em outro servidor, definir explicitamente
`ARKHE_TEST_FIREBIRD_HOST`, `ARKHE_TEST_FIREBIRD_PORT`,
`ARKHE_TEST_FIREBIRD_PASSWORD` e `ARKHE_TEST_FIREBIRD_DIR`. O teste cria nomes
aleatórios com prefixo `arkhe-log-teste-`; nunca usa `DB_NAME` para criar dados.
