# IP no log

LOG.IP VARCHAR(45) guarda o IP da conexão recebido pelo backend.
Os oito campos anteriores continuam iguais e os registros antigos permanecem
intactos, com IP nulo. A lista e o detalhe da auditoria exibem o campo IP.

A função é somente:

```python
def obter_ip():
    if has_request_context():
        return request.remote_addr
    return None
```

registrar_log usa essa função no INSERT direto. O hook da requisição passa o
mesmo valor para ARKHE_IP_LOG, usado pelas 33 triggers. Fora de uma requisição
HTTP, o IP fica nulo. Na hospedagem com proxy, o endereço recebido pode ser o
do proxy. Headers enviados pelo cliente não substituem o valor.

Não há componente local, atalho, endpoint de cadastro de IP ou cookie extra.
As duas regras financeiras, os resumos, permissões e histórico não mudam.

Para a primeira instalação do campo, conferir com
python scripts/aplicar_log_ip.py e aplicar com --apply. O aplicador faz backup
dos dois bancos e salva as fontes anteriores antes da migração. Depois de o
campo e as triggers estarem instalados, as alterações da função são somente
publicação de código e não exigem outra migração de banco.
