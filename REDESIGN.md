# Revis�o de UI/UX - outubro de 2026

## Diagn�stico e plano antes da implementa��o

Stack: FastAPI, PostgreSQL/Neon, HTML/CSS/JavaScript sem framework. O index.html atende a p�gina comercial, login/cadastro, painel do dono/profissional, configura��es, equipe/convites, bloqueios, assinatura, gest�o do SaaS, reserva p�blica, reserva privada, recupera��o/valida��o de e-mail, termos, privacidade e suporte. Produtos e Caixa usa produtos.html/js/css. Design system, atualiza��o da agenda, imagens e PWA j� s�o compartilhados. interface.html � um arquivo legado sem rota; n�o substituir a aplica��o por ele.

Invent�rio de a��es preservadas: conclus�o/cancelamento/reabertura conforme papel; exporta��o CSV; links privados de reserva; configura��o completa e upload de identidade; convites/revoga��o; bloqueios do dono; assinatura Pix manual/cortesia; opera��es e backup do administrador; cat�logo/varia��es/pre�os/custos; vendas com descontos e idempot�ncia; estoque e hist�rico; cancelamento/corre��o de vendas; permiss�es individuais; reservas p�blicas e suas altera��es por link.

Etapas: (1) componentes sem�nticos e shell compartilhado com sidebar recolh�vel e navega��o inferior; (2) in�cio por papel, agenda dia/semana, consulta de clientes a partir das reservas, novo agendamento guiado pela API p�blica existente; (3) relat�rios derivados dos registros reais, equipe e configura��es organizadas; (4) Produtos e Caixa na mesma navega��o, cat�logo/estoque leg�veis, venda e estados de interface; (5) testes de fluxos, permiss�es e auditoria de 360/430/768/1366/1920 pixels.

Limites do escopo: o backend possui tr�s estados de reserva (agendado, conclu�do, cancelado), e o profissional s� pode concluir suas pr�prias reservas. N�o h� cadastro independente de clientes, registro de recebimento de servi�os, caixa com entradas/sa�das avulsas ou fechamento di�rio. N�o inventar dados, pagamentos, lucro l�quido, compara��es ou bot�es para opera��es inexistentes. Clientes s�o identificados pelos contatos das reservas j� autorizadas; novo cliente entra por um agendamento. Receita de servi�os significa atendimentos conclu�dos, n�o confirma��o de pagamento. Preservar essas regras durante o redesign e explicitar as lacunas.

Design: base preta, superf�cies neutras, destaque por barbearia, tipografia do sistema sem download, escala de 4px, �reas de toque de 44px+, �cones SVG �nicos, texto para todos os status, contraste calculado, foco vis�vel, modais com t�tulo/cancelamento/a��o e respeito a movimento reduzido. Sem bibliotecas gr�ficas externas e sem dados fict�cios em produ��o.

