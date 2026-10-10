# Promoções

O dono acessa **Promoções** no painel. Pode publicar, editar, duplicar, pausar,
encerrar e arquivar ofertas; o arquivo mantém reservas e histórico de alterações.
Em **Permissões da equipe**, pode autorizar profissionais a gerenciar ofertas.
Relatórios e confirmação de recebimentos são exclusivos do dono.

Os valores originais vêm do cadastro de serviços. Preço final e desconto em reais
são armazenados em centavos; percentuais são inteiros de 1 a 100. A mesma regra
aplica-se a cada serviço participante. A imagem é opcional e reutiliza Cloudinary;
não há novas credenciais. Arquivos são reduzidos a 1200 px / 250 KB.

Datas e horários usam o fuso de Brasília já adotado pela agenda. A oferta aceita
novas reservas entre início e término e somente para atendimentos nos dias,
horários e profissionais configurados. O atendimento inteiro precisa caber na
faixa. Cancelamentos liberam a cota; reservas concorrentes são serializadas por
barbearia. O preço e as condições são congelados no agendamento. Reagendar mantém
o preço e exige uma data compatível com as condições originais.

No link público, a seção desaparece quando não existem ofertas disponíveis.
Escolher uma oferta usa o fluxo normal de agendamento, sem login ou instalação.

Após concluir um atendimento promocional avulso, abra seus detalhes e escolha
**Registrar recebimento**. Confirme somente depois do pagamento real. Repetir a
confirmação não duplica receita. Uma utilização de assinatura impede cobrança
avulsa. Atendimento com recebimento confirmado não pode ser reaberto/cancelado:
estorno financeiro não é implementado neste módulo.

Relatórios contam reservas pela data do atendimento e receita pela data do
recebimento. O resumo existente de serviços mantém seu critério por data do
atendimento, incluindo a promoção apenas após recebimento confirmado.

Migração aditiva: `promocoes`, `promocao_reservas`, `promocao_pagamentos` e
`promocao_eventos`. Sem alterações em tabelas existentes. Backups incluem as
quatro tabelas; cópias anteriores continuam aceitas. Para reverter o código,
preserve essas tabelas e os valores já gravados em `agendamentos.preco`.

Testes: `PYTHONPATH=. python tests/test_promocoes.py` (SQLite descartável).
`PROMO_TEST_DATABASE_URL` aceita apenas PostgreSQL local e cria schema isolado.
`node tests/test_promocoes_browser.cjs` usa servidor de teste na porta 8788 e
produz capturas em `test-results`. Nunca execute esses testes contra produção.
