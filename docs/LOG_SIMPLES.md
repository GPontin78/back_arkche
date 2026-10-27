# LOG com oito campos

No Firebird separado, os novos registros vão para `LOG`:

| Campo | Conteúdo |
| --- | --- |
| ID_LOG | Identificador gerado no banco de log |
| DATA_HORA | Momento da ação |
| USUARIO | Usuário do sistema, integração autenticada ou usuário SQL |
| TABELA | Tabela alterada ou IA, API, SISTEMA |
| ID_REGISTRO | Registro relacionado, quando houver |
| ACAO | INSERT, UPDATE, DELETE ou evento da aplicação com resultado |
| VALOR_ANTERIOR | Valores anteriores relevantes |
| VALOR_NOVO | Valores novos ou resumo da ação |

Cada uma das 11 tabelas principais mantém três triggers: TG_AI_<TABELA>_LOG para
AFTER INSERT, TG_AU_<TABELA>_LOG para AFTER UPDATE e TG_AD_<TABELA>_LOG para AFTER
DELETE. Cada trigger tem um único EXECUTE STATEMENT ON EXTERNAL DATA SOURCE. Os valores são resumos
fixos em texto, como 44 - 0 - 1 - 0 - 1 para USUARIO. A ordem dos campos aparece em
um comentário na trigger. No UPDATE, ficam o resumo anterior
e o novo, inclusive os campos do resumo que não mudaram. INSERT tem apenas valor
novo e DELETE apenas valor anterior. Não há comparação campo a campo, montagem
de JSON, IF ou CASE nas triggers. Os campos auditáveis seguem a seleção já
usada pelo sistema, sem copiar credenciais, PIN, CVV ou dados pessoais protegidos.
As duas regras financeiras existentes mantêm seus nomes, posições e comportamento.

A IA e a API usam a mesma LOG. A ação indica o evento e seu resultado. O resumo
registra IDs, rota parametrizada e status em texto CAMPO=valor, sem corpo da requisição,
query, headers, áudio ou texto privado da conversa. O log da ação da IA participa
do commit/rollback da própria operação. A integração autenticada é identificada
como INTEGRACAO_API:<id>, inclusive nas alterações feitas por suas chamadas.

## Histórico preservado

AUDITORIA_EVENTO não é apagada, renomeada ou convertida. Os dados e detalhes
originais permanecem intactos. A fila antiga, se houver, termina sua entrega
nessa tabela. Na tela, Ver histórico anterior permite consultar esses registros
no formato de oito campos. O endpoint administrativo anterior continua disponível
para os detalhes legados completos. A LOG tem sua própria numeração; a opção de
histórico seleciona a origem correta ao abrir um registro.

A tela usa /api/v1/admin/auditoria?simples=1 e, para o histórico, historico=1.
Listagem e detalhe retornam exatamente os oito campos em minúsculas. O acesso
continua exclusivo do administrador; os demais endpoints e permissões da IA/API
mantêm seus contratos.

## Aplicação

1. Publicar o Python, compatível com as duas versões.
2. Executar python scripts/aplicar_log_simples.py para conferir sem alterar.
3. Executar python scripts/aplicar_log_simples.py --apply. Faz backup dos dois
   bancos e salva rollback-log-simples.sql antes de criar a LOG.
4. A criação da LOG é aditiva. A troca das 11 triggers e do gravador Python é
   confirmada num único commit no principal. O marcador privado ORIGEM_ID em
   CONFIGURACAO_LOG recebe o sufixo -simples nesse mesmo commit.
5. Publicar a tela que usa os oito campos e verificar o catálogo e o acesso.

Não há alteração de credenciais, dados financeiros, sequência antiga ou histórico.
O rollback restaura as fontes anteriores e seu marcador sem remover a LOG nem os
novos registros. O aplicador recusa fontes ou estrutura diferentes das estudadas.
A garantia de transação comum do EDS permanece a mesma da instalação anterior.

## Validação

Os testes criam dois bancos descartáveis e cobrem a estrutura exata de oito campos,
33 operações nas 11 tabelas, valores alterados, nulos, rollback, histórico, IA,
identidade da integração e omissão de dados privados. A resposta do modelo da IA
é simulada; persistência Firebird e transação EDS são reais. Não há operações
financeiras de QA no banco online.

## Triggers em texto (015)

A migração 015 troca apenas as fontes das 11 triggers. A LOG continua com os mesmos
oito campos; os dados, credenciais e duas regras financeiras são preservados.
Nessa versão anterior, a trigger USUARIO tinha 33 linhas, três variáveis de conexão,
CASE para a operação e um INSERT externo. O ID do registro fica na sua coluna, sem repetição no resumo.

Publicar o Python que aceita valores em texto e os JSONs antigos. Conferir com
`python scripts/aplicar_log_simples.py --texto` e aplicar com
`python scripts/aplicar_log_simples.py --texto --apply`. O aplicador confere as
fontes, faz backup dos dois bancos e salva o rollback antes da troca em um commit.
Não altera o marcador privado de versão, a estrutura da tabela ou os registros.
A tela já aceita texto e continua abrindo os registros anteriores em JSON.

## Três triggers por tabela (016)

A migração 016 substitui as 11 triggers combinadas por 33 triggers de LOG nas mesmas
11 tabelas principais. INSERT usa apenas NEW e grava VALOR_ANTERIOR nulo; DELETE usa
apenas OLD e grava VALOR_NOVO nulo; UPDATE grava os dois resumos fixos. A operação
fica escrita diretamente no INSERT externo, sem CASE ou escolha do evento em execução.
Continuam os oito campos, a conexão configurada, a transação comum, os logs de IA/API
e as duas triggers financeiras existentes.

Conferir com `python scripts/aplicar_log_simples.py --tres` e aplicar com
`python scripts/aplicar_log_simples.py --tres --apply`. O aplicador salva as fontes
anteriores e faz backup dos dois bancos. A remoção das 11 combinadas e a criação das
33 separadas são confirmadas na mesma transação. Se falhar, o rollback mantém as 11
anteriores. O script de retorno remove as 33 e restaura as fontes anteriores sem
apagar os registros. A conferência recusa misturas, alterações inesperadas ou
triggers desativadas e a reaplicação da versão atual não faz alterações.

## Modelo direto do exemplo (017, versão atual)

As 33 triggers passam a declarar V_USUARIO e as variáveis V_ANTIGO/V_NOVO necessárias
à operação, atribuir seus valores e executar o INSERT com parâmetros posicionais ?.
Os resumos concatenam os campos auditáveis com ' - ', incluindo o ID, na ordem
comentada na trigger. Usam VARCHAR(2000), sem cortar o resumo em 50 caracteres.
INSERT grava o anterior nulo; DELETE grava o novo nulo; UPDATE grava ambos.

O usuário continua sendo o autor autenticado ou a integração validada da API, com
CURRENT_USER como alternativa para SQL direto. Usar o dono do registro como autor
poderia atribuir uma alteração administrativa à pessoa errada.

O destino, usuário e senha são lidos da configuração existente pelo aplicador e
escritos diretamente no ON EXTERNAL DATA SOURCE das triggers, como no exemplo.
A migração versionada contém marcadores para evitar publicar credenciais. Deve
ser aplicada por `python scripts/aplicar_log_simples.py --modelo --apply`; sem
--apply, a conferência é somente leitura. Alterar a configuração da conexão
exige reaplicar o DDL correspondente; as triggers deixam de consultá-la a cada linha.

Mantém os nomes TG_AI/TG_AU/TG_AD_<TABELA>_LOG para preservar as regras financeiras,
inclusive TG_AI_COMPRA. WITH COMMON TRANSACTION acompanha commit/rollback da
operação. O aplicador faz backup dos dois bancos e salva as fontes anteriores.
A migração troca apenas as fontes na mesma transação, preservando a tabela de
oito campos, os dados existentes, os logs de IA/API e as duas triggers financeiras.
