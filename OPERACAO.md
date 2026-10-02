# Operação do BarberSaaS

## Recursos entregues

- Recuperação de senha e confirmação de e-mail, com integração Resend preparada. O envio depende da configuração abaixo.
- Folgas, férias e feriados por profissional ou para toda a barbearia, em **Painel → Folgas e bloqueios**. O período final é exclusivo: um bloqueio até 12h permite começar às 12h. Reservas existentes precisam ser resolvidas antes de bloquear.
- Link privado para o cliente cancelar ou mudar uma reserva futura. Ele aparece após reservar. O dono pode gerar outro em **Agenda → Link para o cliente**; um novo link invalida o anterior.
- Histórico dos Pix confirmados, em **Gerenciar assinaturas**. A mensalidade segue R$ 90, com conferência manual no banco.
- Download de cópia completa no painel administrativo, com confirmação da senha atual, e ferramenta de restauração em banco novo.
- Páginas **/termos**, **/privacidade** e **/suporte**. Novos cadastros registram versão e momento do aceite. Contas anteriores não recebem um aceite fictício.

## Ativar e-mails

### Brevo: opção inicial sem domínio próprio

1. Termine o cadastro da Brevo usando dados reais da organização e escolha o plano gratuito.
2. Em **Configurações → Remetentes**, cadastre **Grupo Havo** e **grupohavo061@gmail.com** e confirme o código recebido no e-mail.
3. Sem domínio próprio, a Brevo pode substituir o endereço de envio por um endereço técnico dela. É uma solução temporária: teste a entrega e o spam. [Explicação oficial](https://help.brevo.com/hc/en-us/articles/14925263522578-Comply-with-Gmail-Yahoo-and-Microsoft-s-requirements-for-email-senders).
4. Gere uma chave **API** da Brevo. Não use a chave SMTP. Insira diretamente no Render, sem enviar pela conversa ou colocar no GitHub.
5. Em **Render → barbearia-sistema → Environment**, configure:

   | Nome | Valor |
   |---|---|
   | `EMAIL_PROVIDER` | `brevo` |
   | `BREVO_API_KEY` | Sua chave API inserida por você |
   | `EMAIL_FROM` | `Grupo Havo <grupohavo061@gmail.com>` |
   | `PUBLIC_BASE_URL` | `https://barbearia-sistema-rj6p.onrender.com` |

6. Salve e publique. Teste **Enviar confirmação** no painel da sua própria conta. Confira a entrega e os registros transacionais da Brevo antes de testar **Esqueci minha senha**. A integração usa HTTPS; não depende de conexões SMTP.
7. O plano gratuito tem limite diário. [Limites atuais da Brevo](https://help.brevo.com/hc/en-us/articles/208580669-FAQs-What-are-the-limits-of-the-Free-plan). A conta pode exigir verificação/ativação do envio; a configuração das variáveis, sozinha, não prova a entrega.

### Resend: alternativa para quando tiver domínio

O site funciona sem este envio; até configurar, o usuário recebe uma informação clara e o contato do suporte. A verificação de e-mail ainda não bloqueia o login. Os testes simulam o provedor: não confirmam entrega real em caixas de entrada.

1. Crie/accesse uma conta no [Resend](https://resend.com).
2. Cadastre e verifique um domínio que você possui, seguindo os registros DNS apresentados pelo Resend. Para enviar a clientes reais, não use Gmail como endereço remetente. O Resend exige um domínio próprio verificado; se você ainda não tem domínio, a integração pode aguardar. [Documentação de domínios](https://resend.com/docs/dashboard/domains/introduction).
3. Crie uma chave com permissão de envio, preferencialmente restrita ao domínio. [Documentação das chaves](https://resend.com/docs/dashboard/api-keys/introduction).
4. No Render, abra o serviço **barbearia-sistema → Environment** e configure `EMAIL_PROVIDER=resend` e:

   | Nome | Valor |
   |---|---|
   | `RESEND_API_KEY` | Sua chave, inserida diretamente no Render |
   | `EMAIL_FROM` | `Grupo Havo <acesso@SEU-DOMINIO>` usando o domínio verificado |
   | `PUBLIC_BASE_URL` | `https://barbearia-sistema-rj6p.onrender.com` |

5. Salve e publique as variáveis. Não envie a chave por conversa e não a coloque no GitHub. Não habilite rastreamento de cliques nas mensagens de autenticação.
6. Entre no painel e clique em **Enviar confirmação**. Confira a entrega e o spam. Clique no botão da página aberta pelo e-mail. Teste **Esqueci minha senha** na sua própria conta. A senha nova deve ser inserida por você.
7. Se falhar, confira os registros de envio do Resend e o contador de falhas no painel administrativo. A aplicação não registra chaves nem links privados nos logs.

Links de recuperação valem 20 minutos; de confirmação, 24 horas. Um novo envio substitui o link anterior da mesma finalidade. Redefinir a senha encerra as sessões da conta. A contratação do domínio, se necessária, é separada dos planos de hospedagem e banco; não é feita automaticamente por esta integração.

## Cópias e recuperação

O download no painel é **manual**. A rotina diária criptografada do GitHub está descrita em **BACKUP.md** e depende de configurar `BACKUP_DATABASE_URL` e confirmar a primeira execução bem-sucedida; publicar o workflow não confirma sua ativação. Ela guarda somente arquivos criptografados por 30 dias e ensaia a restauração em PostgreSQL temporário. Guarde a chave privada separadamente. Nunca publique JSON aberto no GitHub: contém nomes, telefones, reservas, pagamentos e hashes das senhas.

1. Entre em **/gestao** com a conta administradora, procure **Cópia de segurança**, informe sua senha atual e baixe o arquivo. Confira que ele foi salvo. Depois clique em **Baixar verificação da cópia** e guarde também o arquivo `.sha256` junto do JSON.
2. A cópia preserva lojas, contas, equipe, assinaturas, pagamentos, reservas, bloqueios, confirmações de e-mail, aceites e hashes dos links dos clientes. Não inclui chaves do Render/Neon/Resend, sessões, convites ou links temporários de recuperação.
3. Use `restaurar_backup.py` para validar o formato sem alterar banco:

   ```text
   python restaurar_backup.py backup-barbersaas-AAAA-MM-DD.json
   ```

4. Para ensaiar a recuperação, use um arquivo SQLite **novo**:

   ```text
   python restaurar_backup.py backup-barbersaas-AAAA-MM-DD.json --sqlite-novo ensaio-recuperacao.db
   ```

5. Para recuperar na nuvem, crie um PostgreSQL separado, sem tabelas. Instale as dependências do projeto. Configure `RESTORE_DATABASE_URL` diretamente no ambiente local privado com a conexão desse banco novo e execute:

   ```text
   python restaurar_backup.py backup-barbersaas-AAAA-MM-DD.json --postgres-vazio
   ```

   A ferramenta recusa PostgreSQL que tenha tabelas e recusa sobrescrever arquivos SQLite. Não use o banco em operação como destino. O argumento opcional `--sha256 SOMA` verifica a integridade quando você conservou a soma original junto da cópia; sem a soma, a validação confere estrutura e vínculos, mas não prova que o arquivo não foi alterado.

6. Rode a aplicação separadamente contra o banco recuperado. Verifique contagens, login, configurações, reservas e histórico. Senhas são preservadas; sessões e convites temporários não são recuperados. Links privados de reservas existentes continuam válidos se você ainda possui os links originais.
7. Somente depois de conferir a recuperação, altere `DATABASE_URL` no Render para o banco recuperado e publique. Preserve o banco anterior até confirmar o resultado. Reservas feitas depois do momento da cópia precisam ser conciliadas: não estarão no arquivo antigo.

O ensaio com dados fictícios em SQLite confirmou login e criação de novas reservas depois da restauração. Em 2 de outubro de 2026, um snapshot nativo do Neon foi restaurado em branch separada e suas tabelas foram consultadas, sem trocar o banco do Render. Esse ensaio nativo não valida sozinho a recuperação do JSON: a validação automática do GitHub restaura dados fictícios em PostgreSQL e verifica login e novas reservas; cada backup real também é restaurado em PostgreSQL temporário antes de publicar o arquivo criptografado. Confira os resultados das execuções antes de qualquer troca em produção.

## Termos e privacidade

Identificação autorizada: **Grupo Havo — Carlos Roberto Guilherme da Silva Junior**, **grupohavo061@gmail.com**, **(61) 98133-2994**. CNPJ e endereço comercial não foram informados e não foram inventados.

As páginas explicam a cobrança manual, responsabilidades da barbearia, acesso da equipe, mensagens manuais, provedores e direitos sobre dados. O texto é uma versão inicial para revisão conforme o negócio crescer, não uma certificação jurídica. [Texto oficial da LGPD](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709compilado.htm).

## Verificação técnica

Execute os arquivos `tests/test_*.py` separadamente, com as dependências de desenvolvimento instaladas. Eles usam bases temporárias e dados fictícios. A suíte cobre cadastro/login, cobrança, equipe, WhatsApp individual e os novos recursos. Os testes não conferem recebimento bancário real nem entrega de e-mail real.
