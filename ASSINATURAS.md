# Assinaturas dos clientes da barbearia

Este módulo é independente do plano de R$ 90 do SaaS. Usa os clientes já identificados pelo WhatsApp nos agendamentos da barbearia.

## Operação

1. Abra **Assinaturas de clientes → Planos** e crie um plano. Selecione serviços e informe a quantidade por ciclo ou marque Ilimitado.
2. Abra **Clientes → histórico do cliente → Assinatura → Cadastrar em um plano**. A adesão cria uma cobrança pendente. O cliente precisa possuir um agendamento no cadastro existente; não há cadastro paralelo.
3. Confira o recebimento real do dinheiro. Em **Ver assinatura → Confirmar pagamento**, o dono registra a data e a forma. O sistema não transfere dinheiro nem consulta bancos.
4. A agenda identifica o plano e os serviços incluídos no ciclo atual pago. Ao concluir um atendimento incluído, confirme **utilização da assinatura**. Cancelamentos e reservas pendentes não consomem créditos.
5. Após o limite, o atendimento pode ser concluído como avulso. A mensalidade confirmada entra no caixa uma única vez; o valor dos serviços incluídos não é somado novamente.
6. Em **Permissões**, o dono concede consulta, cadastro, utilização, histórico e consulta financeira aos acessos de profissionais existentes. Alteração de preço, plano e confirmação de pagamento são exclusivas do dono.

## Ciclos e histórico

- O período inicia na data da adesão. O fim é exclusivo: um ciclo 07/10 a 07/11 cobre até 06/11. Ciclos mensais mantêm o dia da adesão, ajustando meses mais curtos.
- Renovação antecipada cria um ciclo futuro pendente sem retirar os benefícios do ciclo atual pago.
- Com renovação habilitada, o primeiro acesso à agenda/assinatura após o vencimento gera a próxima cobrança pendente. Não existe confirmação automática de pagamento ou rotina que cobre cartões.
- Cada ciclo mantém cópia dos serviços, limites e valores. Alterações do plano valem para ciclos criados depois. Troca de plano da adesão vale para o próximo ciclo ainda não criado.
- Pausar não estende as datas. Retomar exige ciclo pago dentro do período. Cancelar preserva pagamentos e utilizações; cobranças pendentes são canceladas, sem estornar dinheiro recebido.
- Corrigir um atendimento concluído exige o dono: reabrir/cancelar estorna o crédito no histórico. Uma nova conclusão registra outra utilização; o registro anterior não é apagado.
- Comissões preservam o percentual e valor original do agendamento já existente. A mensalidade não gera comissão de produto; política de comissão de assinaturas deverá ser definida separadamente.

## Financeiro

Mensalidades entram pelo dia do recebimento confirmado; serviços avulsos pelo dia do atendimento concluído; produtos seguem as vendas confirmadas já existentes. Essa diferença de datas é intencional. O resumo não representa lucro líquido.

O relatório de assinaturas filtra recebimentos pela data do pagamento e pendências pela data do vencimento. Usa centavos inteiros, guarda o responsável e impede duplicação concorrente. Campos de provedor/referência externa ficam disponíveis para futuras integrações, sem gateway ativo.

## Implantação e recuperação

A instalação cria apenas tabelas/índices novos e não modifica preços, clientes ou agendamentos anteriores. Backups passam a incluir os cinco conjuntos mensal_* e a restauração aceita backups antigos sem esse módulo.

**Não retorne à versão anterior durante operação com assinaturas**, pois ela não reconhece os créditos e poderia voltar a somar serviços incluídos. Para corrigir uma publicação, prefira uma correção nesta estrutura preservando as tabelas. Se for necessário voltar ao código anterior, interrompa a conclusão de atendimentos de assinantes até a correção; mantenha o banco e o backup completos, sem apagar o histórico ou restaurar sobre o banco em uso.

Os testes usam somente SQLite temporário e PostgreSQL local descartável do GitHub. Nenhuma credencial de produção é necessária. Os testes de navegador geram capturas nos temas claro/escuro em 390, 768 e 1440 px.
