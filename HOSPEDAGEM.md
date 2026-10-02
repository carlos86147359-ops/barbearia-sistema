# Hospedagem gratuita para começar

Configuração preparada: Render Free para executar o servidor e Neon Free para guardar os agendamentos em PostgreSQL. O computador pode ficar desligado. Ainda não foi publicado.

1. Crie uma conta no Neon (https://neon.com) e um projeto no plano Free. A conexão fornecida no painel contém uma senha: mantenha-a privada.
2. Coloque esta pasta em um repositório privado do GitHub, sem senhas nem bancos locais.
3. No Render (https://render.com), crie um Web Service ligado ao repositório, com ambiente Docker e plano Free. Configure a pasta raiz se o projeto estiver em uma subpasta.
4. Nas variáveis do Render, configure DATABASE_URL com a conexão do Neon, mantendo as opções de segurança da URL. Não é necessário disco persistente. As tabelas são criadas automaticamente.
5. O Render fornece um endereço HTTPS; não é necessário comprar domínio.

O Render gratuito suspende o servidor após 15 minutos sem acesso. A primeira visita depois disso pode demorar. Ambos os serviços possuem limites de uso; mantenha os planos gratuitos e confira suas condições antes de ativar. Não há garantia de disponibilidade contínua.

Documentação: https://render.com/docs/free e https://neon.com/pricing.

Sem DATABASE_URL, a aplicação usa SQLite para testes locais. Não use essa opção na hospedagem gratuita: seus arquivos são temporários. As reservas locais não são migradas automaticamente para o Neon.

Antes de liberar para clientes, implemente login e permissões dos painéis. Hoje as rotas de listagem e conclusão estão sem autenticação. A adaptação PostgreSQL ainda precisa de teste com um banco real.
