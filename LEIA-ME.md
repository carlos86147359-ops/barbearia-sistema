# BarberSaaS — agenda local

Instale Python 3.10 ou superior. Nesta pasta, execute:

```
python -m pip install -r requirements.txt
python servidor.py
```

Abra http://localhost:8000. Os painéis ficam em /barbeiro e /admin.

O banco barbearia.db é criado nesta pasta. Para aproveitar um banco antigo, faça uma cópia de segurança e copie o banco para esta pasta antes de iniciar. A atualização preserva as reservas antigas e adiciona os campos da agenda; conclusões que existiam apenas na memória do navegador não podem ser recuperadas. Datas antigas inválidas precisam ser corrigidas antes da inicialização.

Regras iniciais: corte e barba duram 60 minutos; combo dura 120 minutos. Expediente das 9h às 12h e das 14h às 19h, todos os dias. Ajuste serviços, valores, profissionais e horários em servidor.py. As reservas concluídas continuam ocupando seu período. Receita e comissões consideram atendimentos concluídos; o saldo mostrado não desconta outras despesas.

WhatsApp: o botão abre uma mensagem para o cliente, que precisa ser enviada manualmente. Não existe envio automático.

Esta versão é para uso e testes locais. Login e separação dos dados entre barbearias ainda precisam ser implementados antes da disponibilização pública como SaaS. A aparência usa recursos externos (Tailwind e fontes), que precisam de internet.
