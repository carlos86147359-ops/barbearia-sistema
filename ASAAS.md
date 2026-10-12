# Grupo Havo — Asaas Sandbox

Esta primeira entrega é exclusiva de homologação. A API de produção é bloqueada
no código. Somente donos presentes em ADMIN_EMAILS veem a área de testes em
Plano e assinatura. O Pix manual, cortesias e limites de acesso permanecem intactos.
Pagamentos fictícios não escrevem em assinaturas/pagamentos nem no caixa da loja.

## Configuração privada no Render

- ASAAS_ENV=sandbox
- ASAAS_API_KEY: chave Sandbox, sem autorização de saques
- ASAAS_WEBHOOK_TOKEN: segredo aleatório de pelo menos 32 caracteres, diferente da API Key
- PUBLIC_BASE_URL: URL HTTPS pública existente

Webhook Sandbox: POST /api/saas/webhook. Configurar authToken igual a
ASAAS_WEBHOOK_TOKEN; versão 3, envio sequencial. Selecionar eventos de Checkout,
assinaturas e pagamentos presentes em cobranca_saas.EVENTS. A resposta de sucesso
é HTTP 200 após persistir um envelope mínimo, sem CPF, endereço ou cartão.
Configurar somente após publicar a rota. API Key nunca é token do webhook.

## Fluxo de teste

1. Administrador entra no SaaS, Plano e assinatura → Asaas Sandbox.
2. Criar checkout; confirmar no modal; abrir checkout hospedado pelo Asaas.
3. Usar somente dados fictícios/cartões de teste oficiais do Sandbox.
4. Após pagamento, conferir histórico e situação; botão Sincronizar é recuperação.
5. Testar recusa, renovação, cancelamento e fila nos logs do Asaas.
6. Confirmar que a validade REAL da conta e o financeiro da loja não mudaram.

Não é criada assinatura só por visitar retorno/successUrl. Vinculação inicial usa
GET /payments?checkoutSession=ID; nunca associação por e-mail informado no checkout.
O contrato só recebe uma assinatura depois de verificar cliente, ciclo, valor e
forma de pagamento pela API. Retentativas e eventos antigos leem estado atual.
Um timeout de POST deixa a operação incerta e bloqueia novas criações; não repetir
sem conferir o webhook CHECKOUT_CREATED e os logs do Asaas. Não há retry automático
de criação. IDs únicos e trava transacional protegem requisições simultâneas.

A fila é persistida e retomada no startup; reconciliador roda por minuto enquanto
o serviço estiver ativo, com conferência financeira por hora e limite de trabalho.
No Render Free, suspensão do serviço pode atrasar entregas. Monitorar filas pausadas
no Asaas; este mecanismo não oferece disponibilidade contínua nem substitui um
agendador externo/worker sempre ativo para o lançamento comercial.

As quatro tabelas saas_* estão incluídas no backup/restauração. Backups anteriores
continuam aceitos. Chaves não fazem parte dessas tabelas.

## Limites desta fase / antes da produção

- Nenhuma conta real é liberada, suspensa ou cobrada automaticamente.
- Troca segura do cartão ainda depende de homologar a jornada hospedada/tokenizada;
  não se coleta cartão no frontend ou backend do SaaS nesta entrega.
- Relatório administrativo exibe testes; MRR real é zero, sem misturar com Pix.
- Não foi aplicada a campanha de R$60 por três meses; plano de teste é R$90/mês.
- Definir tolerância, calendário de acesso pago, cancelamento ao fim do período,
  estornos/chargebacks e migração das contas manuais antes de habilitar produção.
- Validar conta produtiva, tokenização com Asaas, checkout móvel, renovação real,
  atualização de cartão e disponibilidade/monitoramento. Atualizar termos e privacidade.
- Não basta trocar ASAAS_ENV: produção exige implementação e autorização separadas.

Fontes: https://docs.asaas.com/docs/checkout-com-assinatura-recorrente
https://docs.asaas.com/reference/listar-cobrancas
https://docs.asaas.com/docs/sobre-os-webhooks
https://docs.asaas.com/docs/faq-assinaturas

### Conta separada de homologação
ASAAS_SANDBOX_TEST_EMAILS aceita uma lista de e-mails de proprietários de teste, separados por vírgula. Por padrão a lista é vazia. Ela libera somente operações Sandbox, nunca o painel administrativo Grupo Havo ou acesso real à agenda. Cadastre uma conta separada e autorize apenas o e-mail dessa conta no Render. Não use e-mails de clientes reais.

Rejeições HTTP 400 da criação de checkout encerram a tentativa sem repetir automaticamente. Timeouts continuam incertos. Para tentativas antigas incertas, o administrador pode encerrar no painel de homologação SOMENTE após conferir HTTP 400 nos logs privados do Asaas. Essa exceção é auditada, bloqueada fora do Sandbox e indisponível para donos de barbearias.

A vinculação inicial recupera a cobrança pelo ID de evento e confirma checkoutSession, assinatura, cliente, valor e ciclo pela API. Para conciliação manual de eventos antigos, busca até 10 IDs de cobrança recebidos após a criação do contrato; esse limite de homologação precisa de índices de correlação antes de produção em escala.
