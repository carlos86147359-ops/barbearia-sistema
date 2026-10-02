# BarberSaaS — contas de barbearias

Cada dono cria sua conta em /cadastro, configura o negócio em /painel e compartilha /b/endereco-da-barbearia. Serviços, preços, duração, profissionais, comissão, dias e períodos de funcionamento são editáveis pelo dono. As reservas mantêm o preço, duração e comissão da criação.

O cliente agenda sem precisar criar conta. O dono consulta, conclui, cancela e reabre reservas, e pode exportar os dados em CSV. Cancelar libera o horário; reabrir verifica se outra reserva o ocupou. Os dados de uma barbearia não são disponibilizados a contas de outra.

## Executar localmente

Python 3.10 ou superior:

```
python -m pip install -r requirements.txt
python servidor_pronto.py
```

Abra http://localhost:8000. Sem DATABASE_URL, o banco SQLite fica nesta pasta. Com DATABASE_URL, usa PostgreSQL. Em Render, a variável é obrigatória. O serviço atual usa o comando uvicorn servidor_pronto:app --host 0.0.0.0 --port $PORT.

## Hospedagem

Render Free executa o servidor e Neon Free mantém o banco. Não é necessário disco persistente. O servidor pode entrar em suspensão após inatividade; os planos possuem limites. Mantenha ambos os serviços no plano gratuito. DATABASE_URL deve ficar apenas nas variáveis protegidas do Render.

A versão anterior usava uma agenda única sem contas. Os dados antigos permanecem identificados como demonstração e não são atribuídos automaticamente a donos recém-cadastrados. A demonstração não aceita reservas novas.

## Operação e limites desta versão

A conta do dono controla a barbearia. Ainda não há contas separadas de funcionários, cobrança de assinatura ou recuperação automática de senha por e-mail. Os e-mails não são verificados; o dono deve guardar sua senha com cuidado. Notificações WhatsApp abrem mensagens para envio manual, sem envio automático.

Há sessões de 12 horas, senhas armazenadas com hash, proteção contra alterações por outra origem, limitação básica de tentativas e isolamento por estabelecimento. A recuperação de dados do Neon depende do plano; exportar o CSV das reservas periodicamente dá uma cópia para consulta, mas não substitui backup completo de contas e configurações.
