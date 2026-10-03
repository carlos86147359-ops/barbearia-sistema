# Reformulação da interface

## Estrutura observada antes das alterações

- Python/FastAPI (`app.py`), iniciado por `servidor_pronto.py`.
- PostgreSQL/Neon em produção; SQLite apenas para desenvolvimento e testes.
- HTML e JavaScript sem framework em `index.html`; PWA em `pwa.js`, `sw.js` e `pwa.py`.
- `/b/{slug}`: reserva pública; `/minha-reserva`: cancelamento/reagendamento pelo link privado.
- `/painel`, `/admin`, `/barbeiro`: mesma entrada, diferenciada pelo papel da sessão.
- `/gestao`: administração do SaaS; login, cadastro, convite, recuperação, confirmação de e-mail, termos, privacidade e suporte têm rotas próprias.
- Agenda, configurações, equipe, bloqueios, comissão, assinatura e backup já existem. O profissional hoje só pode consultar sua agenda e concluir seus atendimentos. Alterar essa autorização exige uma etapa separada.

## Referência e direção

A imagem enviada orienta a composição: preto, superfícies neutras, dourado, cards compactos, ícones de traço e navegação específica por papel. Não copiar avaliações, fotos, faturamento ou nomes fictícios para a produção. Fotografias e identidade vêm da configuração de cada estabelecimento; usar iniciais e ilustração abstrata quando não existirem.

## Plano em etapas

1. **Cliente e base visual:** tokens compartilhados, componentes, página da barbearia, serviço, profissional (inclusive qualquer profissional), calendário, horários, dados, revisão e sucesso. Configuração opcional de identidade visual sem migração de tabelas.
2. **Profissional:** aplicar navegação inferior, início com próximo atendimento, agenda, detalhes/histórico dos próprios clientes, financeiro individual e perfil. Implementar falta, reagendamento e bloqueios com autorização explícita por papel e testes de isolamento, sem reutilizar acesso do dono.
3. **Dono:** sidebar, indicadores derivados de reservas reais, gráfico de receita concluída, agenda por profissional, clientes, serviços, financeiro, relatórios, página pública e configuração/plano. Preservar exportação, convites, onboarding e assinatura.
4. **Administração do SaaS:** harmonizar gestão e pagamentos mantendo confirmação manual de Pix e backup.

Cada etapa passa por testes funcionais e conferência mobile/desktop antes de publicação. Esta entrega implementa a etapa 1; não apresenta ações ainda inexistentes como se funcionassem.

## Design system

`design-system.css` define tokens de superfície, texto, destaque, borda, raio, espaçamento e foco. A cor opcional da barbearia é aplicada só à experiência pública; calcular texto claro/escuro para contraste.

`design-system.js` contém helpers únicos para ícones SVG, avatar por iniciais, escolha selecionável, estado vazio/loading, resumo e calendário acessível. Botões/inputs/cards/badges/seletores usam classes compartilhadas. Modais, navegação inferior, sidebar, tabelas e gráficos têm estilos base para as próximas etapas; não há telas falsas nem biblioteca externa.

Calendário respeita dias de funcionamento e limite de 180 dias. Disponibilidade continua vindo da API existente. “Qualquer profissional” consulta os profissionais em grupos limitados, reúne horários e mostra o profissional concreto na revisão. A confirmação usa o endpoint existente, que valida disponibilidade e concorrência novamente; um conflito retorna à escolha de horário.

URLs opcionais de logo/capa usam HTTPS; Instagram aceita apenas perfil no domínio Instagram. Nome, preços, duração, profissionais, endereço e contatos nunca são fixados no frontend. Não são adicionados upload pago, serviços de imagem ou dependências externas.
