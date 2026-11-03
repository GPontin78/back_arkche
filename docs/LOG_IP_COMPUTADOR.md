# IP interno do computador

O novo campo `LOG.IP VARCHAR(45)` recebe o endereço do adaptador usado pelo PC para
acessar o banco. Os outros oito campos continuam iguais. Os registros anteriores
permanecem intactos, com IP nulo.

O componente `componente_local/abrir_banco.pyw` roda no próprio computador, consulta
o endereço local da conexão de rede e abre o site. O IP vai no fragmento da URL;
o frontend o envia uma vez ao backend e remove o fragmento antes de abrir o sistema.
O componente termina depois de abrir o navegador. Não mantém servidor, porta local
ou serviço em segundo plano, nem precisa de pacotes Python adicionais.

O backend valida o endereço e a origem do site, guarda o IP numa sessão assinada
com cookie HttpOnly e usa `obter_ip_computador()` tanto em `registrar_log` quanto
no contexto das 33 triggers. O IP é informado pelo componente do cliente; não é
uma prova de identidade e não altera autenticação, permissões ou limites financeiros.
Requests sem essa sessão têm IP nulo. Headers como X-Forwarded-For e o endereço do
servidor não substituem o IP interno. Consultas SQL diretas sem contexto também
ficam com IP nulo.

## Usar no Windows

O PC precisa ter Python instalado. Execute o instalador com a URL do banco e o
caminho do pythonw.exe, por exemplo:

```powershell
.\componente_local\instalar.ps1 -UrlBanco 'https://arkhe-frontend.zbbquj.easypanel.host/' -Pythonw 'C:\Python\pythonw.exe'
```

O instalador copia o componente para `%LOCALAPPDATA%\Arkhe` e cria o atalho
`Banco Arkhe - IP do PC` na área de trabalho. Se já houver uma instalação, salva
uma cópia antes de substituir. Cada PC precisa do seu próprio atalho.

Abra o banco por esse atalho. Se mudar de Wi-Fi, VPN ou adaptador, reabra pelo
atalho para atualizar o endereço. A captura corresponde ao momento da abertura.
Se o site não conseguir registrar o IP, mostra um aviso antes de iniciar a sessão
do sistema. Os dados financeiros não são enviados pelo componente.

## Atualizar a instalação online

1. Executar `python scripts/aplicar_log_ip.py` para conferir somente leitura.
2. Executar `python scripts/aplicar_log_ip.py --apply`. Faz backup dos dois bancos,
   salva as fontes anteriores e acrescenta IP permitindo nulo no banco separado.
3. O aplicador atualiza apenas as 33 fontes de log, sem recriar as triggers. As
   duas regras financeiras, privilégios, descrições e dados são preservados.
4. Publicar o backend e depois o frontend. Os gravadores antigos continuam
   funcionando durante a implantação porque IP permite nulo.
5. Instalar o atalho nos PCs e conferir o IP na Central de Auditoria.

A criação do campo é confirmada antes das triggers porque são bancos separados.
Se a troca das fontes falhar, o rollback mantém as triggers anteriores e o campo
novo continua nulo, sem apagar registros. O SQL salvo restaura as fontes anteriores;
deixar IP no banco permite retornar o código sem descartar os valores já capturados.
