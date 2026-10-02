# Backup automático do BarberSaaS

## O que foi preparado

Uma cópia por dia pelo GitHub Actions, às **03h17 de Brasília** (horário previsto, sujeito a atraso do GitHub), com retenção de **30 dias**. Funciona sem o seu computador ligado. A ativação depende de inserir a conexão secreta e confirmar a primeira execução bem-sucedida.

Os dados são lidos em uma transação consistente e somente de leitura. A rotina inclui barbearias, contas, equipe, assinaturas, pagamentos, reservas, bloqueios, aceites, confirmações de e-mail e hashes dos links dos clientes. Sessões, convites, tokens de recuperação e chaves de serviços não são incluídos.

Cada execução valida o arquivo e restaura a cópia em um PostgreSQL vazio e temporário dentro do executor do GitHub. Só depois publica o arquivo criptografado com AES-256-GCM e RSA-OAEP. Nenhum JSON com os dados abertos é publicado. O repositório é público: os artefatos criptografados podem ser baixados por quem tem acesso de leitura, mas a chave privada necessária para abri-los fica com você.

## Guardar a chave privada

O arquivo **CHAVE-PRIVADA-BACKUP-GUARDE.pem**, entregue junto deste guia, é necessário para recuperar qualquer backup produzido com a chave pública atual. Guarde duas cópias em locais privados separados, preferencialmente protegidos por senha ou criptografia do dispositivo. Não envie por WhatsApp, não publique no GitHub e não coloque no Render. Se perder essa chave, esses backups não poderão ser abertos. Ela não precisa ficar no computador ligado.

A chave pública `backup-publica.pem` pode ficar no repositório. Ela cifra os arquivos, mas não consegue abri-los.

## Ativação

1. No GitHub, abra **barbearia-sistema → Settings → Secrets and variables → Actions → New repository secret**.
2. Nome: **BACKUP_DATABASE_URL**. Valor: conexão PostgreSQL do Neon com SSL, inserida diretamente por você. Uma conexão de usuário com permissão apenas de leitura é preferível. Não mande a conexão pelo chat. Ao reutilizar a conexão de proprietário, ela também permite escrever no banco, embora a rotina faça somente leitura; mantenha restrito o acesso de escrita ao repositório.
3. Abra **Actions → Backup diario criptografado → Run workflow → main → Run workflow**.
4. Aguarde o resultado verde de todas as etapas, incluindo **Guardar somente arquivos criptografados**. Baixe o artefato para confirmar que ele contém `.cifrado.json` e `.sha256`. Não considere a rotina ativa só porque o segredo foi salvo.
5. Confira regularmente as execuções na aba Actions. Uma falha não substitui a última cópia boa. As notificações de falha dependem das preferências de notificações do GitHub da sua conta.

O GitHub pode atrasar horários e desativar agendamentos em repositórios públicos sem atividade por 60 dias. Verifique a rotina pelo menos semanalmente e reative-a se aparecer desativada. Antes de uma mudança importante, execute **Run workflow** e confira o sucesso. Nunca armazene o backup em texto aberto nos artefatos ou commits.

## Recuperação

1. Baixe e extraia um artefato de uma execução bem-sucedida e confira a soma SHA-256 do arquivo criptografado usando o `.sha256` correspondente.
2. Em ambiente privado, com `requirements.txt` e `requirements-backup.txt` instalados:

   ```text
   python backup_nuvem.py abrir backup-barbersaas-DATA.cifrado.json CHAVE-PRIVADA-BACKUP-GUARDE.pem backup-aberto.json
   python restaurar_backup.py backup-aberto.json
   ```

3. Crie um PostgreSQL separado e vazio. Insira sua conexão em `RESTORE_DATABASE_URL` no ambiente privado e execute:

   ```text
   python restaurar_backup.py backup-aberto.json --postgres-vazio
   ```

4. Rode a aplicação separadamente contra o banco restaurado. Confira login, configurações, agenda e pagamentos antes de trocar qualquer conexão de produção. Sessões e convites temporários não voltam. Reservas criadas depois da cópia precisam ser conciliadas.
5. Preserve o banco anterior até concluir a conferência. Remova arquivos abertos somente após guardar o necessário em local seguro.

## Ensaio realizado no Neon

Em **2 de outubro de 2026**, foi criado um snapshot do banco de produção e restaurado em uma branch separada, sem mudar a conexão do Render. A consulta no banco restaurado encontrou 3 lojas, 2 usuários, 1 agendamento, nenhum funcionário e nenhum pagamento confirmado. Isso valida a restauração nativa do snapshot e a leitura das tabelas; não prova login nem substitui a validação dos backups do GitHub.

O snapshot manual permanece no Neon. A branch de ensaio também permanece separada. O plano mostrou histórico de recuperação de 6 horas e agendamento nativo de snapshots condicionado a upgrade. Não foi contratado plano pago. O snapshot é uma proteção dentro do mesmo provedor; os backups criptografados do GitHub são a cópia externa adicional.

## Limites e conferência

Retenção de 30 dias não é arquivo permanente. Com frequência diária, alterações feitas após a última cópia podem ser perdidas em um incidente. Falta de conexão, indisponibilidade ou atraso do GitHub podem aumentar esse intervalo. Confira também limites de armazenamento e transferência dos provedores conforme crescer o uso.

Referências: [horários e inatividade dos workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule), [acesso aos artefatos](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts).
