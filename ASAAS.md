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


## Produção — oferta com nova contratação consentida

A implementação suporta ambiente production com credenciais separadas:
- ASAAS_ENV=production
- ASAAS_PRODUCTION_API_KEY: chave real sem permissão de saques.
- ASAAS_PRODUCTION_WEBHOOK_TOKEN: segredo exclusivo, aleatório >=32 caracteres.
- ASAAS_PRODUCTION_ENABLED=false durante homologação. true permite novos checkouts.
  Desabilitar esse flag NÃO interrompe webhooks/conciliação de contratos existentes.
- PUBLIC_BASE_URL mantém a URL HTTPS existente.
Não sobrescrever chaves Sandbox. A troca de ambiente só ocorre após testes.

A oferta v1 é R$60/mês, com primeiro vencimento no dia da contratação e endDate
no terceiro vencimento mensal (dois meses após o primeiro). O limite pertence
à recorrência no Asaas, não a um cron que poderia dormir. Depois, o dono deve
autorizar NOVO checkout de R$90/mês; nunca há aumento automático ou reuso do cartão
para essa contratação. Cancelar a oferta não reinicia sua elegibilidade.
saas_condicoes guarda preço/oferta, primeiro e último vencimentos e instante do aceite
vinculado ao contrato/usuário. Os contratos e auditoria preservam o restante da prova.
Uma nova contratação só é permitida quando não há contrato aberto nem período
pago real vigente. Cancelamento não apaga cobranças existentes ou período pago.
Conta de cortesia não recebe oferta nem pode criar cobrança.

O acesso é calculado de saas_cobrancas de produção com status CONFIRMED/RECEIVED,
vencimento já iniciado e periodo_fim futuro. O período termina à meia-noite de
Brasília no próximo aniversário mensal. Recebimento atrasado não muda o calendário
das outras mensalidades. Estorno/chargeback/exclusão retira somente esse recebimento;
Pix anterior e cortesia continuam valendo. Sandbox nunca altera acesso real.
Não há tolerância adicional por inadimplência nesta versão.
As mensalidades das próprias barbearias e o caixa delas não recebem esses valores.

Webhook de produção: POST /api/saas/webhook, somente quando ASAAS_ENV=production,
authToken=ASAAS_PRODUCTION_WEBHOOK_TOKEN, versão 3 e envio sequencial.
Configurar os eventos de cobranca_saas.EVENTS. O endpoint rejeita token Sandbox.
Configurar/publicar primeiro; habilitar novas vendas por último.
A resposta HTTP200 significa envelope persistido; consultar fila e logs de webhook
para confirmar processamento. Monitorar a fila diariamente, especialmente Render Free.
Há processamento após webhook e conciliação persistente enquanto o servidor está ativo.
Render Free pode dormir e atrasar atualização de acesso; recorrência e endDate
são executados pelo Asaas. Recomenda-se instância sempre ativa para operação contínua.
Não há job externo configurado automaticamente nesta alteração.

Testes obrigatórios: tests/test_cobranca_saas.py e tests/test_cobranca_producao.py,
em SQLite e PostgreSQL. Os testes de produção são simulados, sem dinheiro/cartão real.
Antes de habilitar vendas, homologar checkout Sandbox com valor60 e endDate,
geração dos três vencimentos, ausência de quarta cobrança, cancelamento, estorno,
transição via novo checkout90 e interfaces mobile. Um pagamento real de validação,
se desejado, precisa ser executado pelo titular; nunca usar cartão fictício em produção.
A troca de cartão pelo SaaS segue indisponível: não coletamos PAN/CVV.
O histórico contém links hospedados de fatura para consulta/regularização.

Fontes:
https://docs.asaas.com/docs/checkout-com-assinatura-recorrente
https://docs.asaas.com/docs/faq-assinaturas

Homologação da oferta limitada: manter ASAAS_ENV=sandbox e habilitar ASAAS_SANDBOX_PROMO_TEST=true. Isso oferece o mesmo checkout60/endDate somente às contas de teste permitidas; nunca libera acesso real. Desligar o flag após testar. Os testes antigos continuam em R$90 quando esse flag está ausente.


## Mensalidade por PIX

Além da assinatura recorrente no cartão, o painel oferece checkout PIX avulso (billingTypes PIX, chargeTypes DETACHED). Cada confirmação canônica concede um mês; requer novo pagamento ao fim do período e não utiliza Pix Automático.

Reutiliza saas_contratos, saas_condicoes (ofertas pix_60_v1 e pix_90_v1), saas_cobrancas e a fila saas_webhooks. Nenhuma chave nova ou migration destrutiva é necessária. A cobrança mensal quitada fecha o contrato técnico avulso para permitir renovação, mas contract_view mostra quitada/PIX confirmado. Refunds/deleted revogam acesso sem apagar histórico ou reiniciar benefício.

Até três mensalidades PIX promocionais de R$60 por estabelecimento/ambiente. Meses PIX consumidos reduzem os ciclos restantes ao iniciar a oferta no cartão; uma oferta de cartão já utilizada continua sujeita às condições anteriores, sem reinício após cancelamento. O quarto PIX custa R$90, informado antes do aceite. Impede contratação durante período já pago ou recorrência/cartão ativa.

Teste sem rede: tests/test_cobranca_pix.py em SQLite e PostgreSQL isolados. Teste de integração real deve ser feito no Sandbox; não transferir dinheiro real durante homologação. QR Code e copia e cola são exibidos no checkout hospedado do Asaas. Chaves e QR não são fabricados no frontend; redirecionamento nunca comprova pagamento.
