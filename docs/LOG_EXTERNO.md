# Log do sistema

A estrutura atual é a tabela `LOG`, com os oito campos definidos em
[LOG_SIMPLES.md](LOG_SIMPLES.md). `AUDITORIA_EVENTO` permanece como histórico anterior.

## Histórico técnico das migrações anteriores

Cada tabela principal tem uma trigger `TG_AIUD_<TABELA>_LOG`, com
`AFTER INSERT OR UPDATE OR DELETE`. A significa AFTER; I, U e D indicam as três
operações. `INSERTING`, `UPDATING` e `DELETING` identificam o evento em execução.
São **11 triggers nas 11 tabelas principais**: USUARIO, CONTA, MOVIMENTACAO,
COBRANCA, CARTAO, CHAVE_PIX, COMPRA, FATURA, AGENDAMENTO_FINANCEIRO,
RECORRENCIA_FINANCEIRA e ESTORNO_FINANCEIRO. Cada uma lê a configuração e executa
um `INSERT` parametrizado em `AUDITORIA_EVENTO` com `EXECUTE STATEMENT ... ON
EXTERNAL DATA SOURCE ... WITH COMMON TRANSACTION`. Não há procedure geral de log.
As duas triggers financeiras mantêm suas regras e posições.

A aplicação registra uso do sistema, respostas HTTP da IA, API pública e
WhatsApp, com método, recurso, resultado, usuário/conta autenticados e integração
validada. Os eventos semânticos do MAURO e do Pix continuam no Python. Eventos sem alteração de tabela, como consultas e recusas,
são registrados pelo Python. O sucesso das mensagens e confirmações Pix é
auditado antes do commit, na mesma transação da ação.

O log inclui usuário, conta, rota, horário, valor e snapshots de metadados. Não
copia mensagens privadas, áudio, PIN, CVV, senhas, tokens, hashes, documentos ou
chaves Pix. Os IDs das mensagens permitem relacionar o log ao histórico já salvo.

`CONFIGURACAO_LOG` guarda um único destino: datasource, usuário, senha e origem.
O aplicador preenche os valores usando as variáveis `ARKHE_AUDIT_DB_*` já
configuradas, por parâmetros. Não publicar os valores dessa tabela nem conceder
SELECT a usuários de negócio. As próprias triggers recebem SELECT e USAGE na
sequência, sem abrir acesso direto às credenciais. Isso atende também SQL
direto pelo DBeaver nas tabelas principais, sem depender do contexto definido pelo backend.
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
com dados fictícios, testa as 33 operações de trigger, redução/rollback, antes/depois, JSON,
rollback, configuração, falha externa, aliases CREATE/EXECUTE, parcelas e o
fluxo HTTP da IA com resposta simulada. As colunas da fixture foram extraídas do
catálogo online em 26/10/2026; ela não reproduz todos os índices e FKs.

Para testar em outro servidor, definir explicitamente
`ARKHE_TEST_FIREBIRD_HOST`, `ARKHE_TEST_FIREBIRD_PORT`,
`ARKHE_TEST_FIREBIRD_PASSWORD` e `ARKHE_TEST_FIREBIRD_DIR`. O teste cria nomes
aleatórios com prefixo `arkhe-log-teste-`; nunca usa `DB_NAME` para criar dados.

## Redução da instalação já publicada (011 -> 012)

A 011 permanece imutável como histórico. A 012 retira somente as 72 triggers de
log das tabelas auxiliares. Não apaga tabelas, registros, conversas ou logs;
não troca credenciais, destino, sequência nem as duas regras financeiras.
Essa foi a redução intermediária. Instalações novas criam diretamente as 11
triggers unificadas, sem criar as versões anteriores.

Publicar primeiro o Python atualizado. Executar
`python scripts/restringir_log_principal.py` para comparar nomes, tipos,
posições e fontes de todas as triggers. Se corresponder à versão estudada,
`python scripts/restringir_log_principal.py --apply` faz backup dos dois bancos,
salva `rollback-reducao.sql`, reconfere o catálogo e retira as auxiliares num
único commit. Mudanças manuais inesperadas interrompem a aplicação.

O log HTTP usa o modelo da rota e apenas IDs inteiros, sem copiar corpo, query,
headers ou tokens. O feed/status/stream da auditoria não gera log a cada polling;
consultas de detalhes mantêm seu registro explícito. Uma falha tardia no log HTTP
não altera a resposta de uma escrita já confirmada nem oculta uma recusa original.
O log transacional das tabelas principais e das ações semânticas da IA permanece
obrigatório. Alterações SQL diretas nas tabelas auxiliares deixam de ser auditadas.

### Integrações pela API

As integrações usam as chamadas normais da API. A auditoria registra o recurso,
o método, o resultado HTTP e a conta/integração identificada pela autenticação
existente. O fluxo da IA mantém os eventos semânticos da aplicação e as mudanças
nas tabelas principais continuam registradas pelas triggers.

## Uma trigger por tabela (013)

A migração `013_log_uma_trigger_por_tabela.sql` substitui as 33 triggers separadas
por 11 triggers unificadas. Cada uma lê a configuração uma vez e usa um único
`EXECUTE STATEMENT ... ON EXTERNAL DATA SOURCE`; os parâmetros selecionam o evento,
OLD/NEW, resultado e snapshots correspondentes. O log continua indicando INSERT,
UPDATE ou DELETE e gravando os dados anteriores e novos quando aplicável.
As duas regras financeiras seguem separadas, nas posições existentes.

Publicar primeiro `auditoria.py`, compatível com ambas as versões. Executar
`python scripts/unificar_log.py` para conferir o catálogo e depois
`python scripts/unificar_log.py --apply`. O aplicador faz backup dos dois bancos,
salva `rollback-unificacao.sql`, reconfere as fontes e troca todas as triggers
num único commit. Credenciais, sequência, destino e histórico são preservados.
Uma segunda aplicação somente confirma que já está atualizado.

A sintaxe dos três eventos e suas variáveis de contexto está documentada em
[Firebird 4, CREATE TRIGGER](https://www.firebirdsql.org/file/documentation/chunk/en/refdocs/fblangref40/fblangref40-ddl-trigger.html).
