"""Matriz de acesso do WhatsApp. Mantida separada da camada HTTP/Firebird."""

CARGOS_FINANCEIROS = (0, 1, 2)  # Administrativo, Financeiro e Contador.


def capacidades_whatsapp(conta):
    """Retorna apenas as consultas permitidas para a conta e cargo ativos."""
    if conta['tipo_conta'] == 0:
        return {'financeiro': conta['vinculo'] == 'titular', 'rh': False}
    if conta['tipo_conta'] != 1:
        return {'financeiro': False, 'rh': False}
    if conta['vinculo'] == 'proprietario':
        return {'financeiro': True, 'rh': True}
    return {
        'financeiro': conta.get('cargo') in CARGOS_FINANCEIROS,
        'rh': conta.get('cargo') == 3
    }
