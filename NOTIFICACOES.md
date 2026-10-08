# Notificações da equipe
Web Push padrão (VAPID + pywebpush), sem conta Firebase ou aplicativo nativo.
O cliente final continua agendando no navegador, sem instalação ou solicitação de notificações.

## Configuração privada do servidor
Gere uma única vez, em terminal privado: `python gerar_chaves_push.py`.
Guarde os três valores em Environment do Render:
- WEB_PUSH_VAPID_PRIVATE_KEY: segredo privado de 32 bytes, base64url.
- WEB_PUSH_VAPID_PUBLIC_KEY: chave pública P-256 de 65 bytes, base64url.
- WEB_PUSH_VAPID_SUBJECT: mailto:grupohavo061@gmail.com.
Não envie a saída ao chat/GitHub, não use as chaves geradas pelos testes.
Salve e publique. Preserve esse par de chaves em atualizações futuras.
Trocar a chave exige reativar as assinaturas dos dispositivos.
PUBLIC_BASE_URL deve continuar apontando para a URL HTTPS real do SaaS.
PUSH_ALWAYS_ON=true apenas se o serviço realmente permanecer ativo.

A central funciona sem VAPID. A opção de ativar push fica desabilitada até a configuração válida.
Sem essas credenciais, não existe envio real para o celular.

## Usar no celular
Entre na conta individual do profissional pelo link /entrar.
Abra Mais → Notificações (também acessível pelo sino no topo).
Escolha Ativar notificações neste dispositivo e permita os avisos.
O dono precisa selecionar Receber agendamentos de toda a equipe e salvar.
Cada profissional deve usar sua própria conta convidada pelo dono; não compartilhe a senha do dono.
Use outro navegador/celular para fazer uma reserva pública. Confira o aviso e toque para abrir o agendamento.
Teste cancelamento e reagendamento pelo link privado do cliente.
Teste dois profissionais e uma segunda barbearia, sem compartilhar contas.
Permissão bloqueada deve ser liberada nas configurações do navegador.
Faça isso separadamente em cada dispositivo; limite de dez ativos por conta.
Ao sair da conta, o backend desativa este dispositivo. Ao entrar novamente, reative pelo botão.

## Plataformas e hospedagem
Android: navegador compatível com Web Push, HTTPS e permissão do usuário.
iPhone/iPad: iOS/iPadOS 16.4 ou superior, Safari → Compartilhar → Adicionar à Tela de Início;
ative dentro da versão instalada. Essa orientação aparece somente para a equipe.
Desktop: navegador compatível e permissão; sistema/Focus/economia de bateria podem impedir ou atrasar a exibição.
Não há garantia de entrega/horário pelo sistema operacional ou provedor.
O relógio de lembretes e retries roda no servidor, em lotes limitados, a cada minuto.
No Render gratuito o processo pode dormir: não há garantia de lembretes enquanto estiver suspenso.
Não tentamos manter a hospedagem acordada com loops no cliente.
Para lembretes contínuos, use serviço sempre ativo; a fila pendente é recuperada na inicialização.
Lembretes são emitidos uma vez por horário/usuário/antecedência, numa janela de 90 segundos.
Avisos de cancelamento registram que o horário foi cancelado, sem atribuir falsamente a ação ao cliente quando foi o dono.

## Segurança, dados e operação
Tabelas novas: notificacao_preferencias, notificacao_revisoes, notificacao_eventos,
notificacoes, push_dispositivos, push_entregas. Migração aditiva, sem alterar registros antigos.
Eventos e central são persistidos na transação da reserva; envio acontece somente após commit.
Novos dispositivos não recebem retroativamente todos os avisos antigos.
Cada destinatário vem do profissional autenticado/ativo e do dono com opção equipe habilitada.
O dono sem opção equipe não recebe avisos dos demais profissionais; não há papel gestor separado na arquitetura atual.
Não existe endpoint público de disparo. Registro e preferências usam autenticação + CSRF.
Endpoints de push só aceitam HTTPS em provedores conhecidos; redirecionamento HTTP desabilitado.
Assinaturas expiradas (404/410) são desativadas. Falhas transitórias recebem até oito tentativas, com backoff.
Claims no banco e unicidade por evento/dispositivo impedem disparos concorrentes iguais.
O service worker usa IDs/tag e IndexedDB para deduplicar exibição e impedir avisos de outra conta no mesmo navegador.
Não coloque dados privados em cache PWA: apenas conta opaca e IDs ficam no IndexedDB.
Push transmite dados criptografados; conteúdo pode aparecer na tela bloqueada conforme a configuração do celular.
Backups incluem os novos dados, com validação de referências e compatibilidade com cópias antigas.
A chave privada VAPID fica fora do banco/backup. Guarde uma cópia privada segura.
Agendamento é sempre a fonte oficial; falha de push não altera status nem receita.

## Validação automatizada
tests/test_notificacoes.py: SQLite e PostgreSQL descartáveis, envio substituído por provedor simulado.
tests/test_push_worker.cjs: eventos push/click, deduplicação, conta, logout e falha de exibição.
tests/test_notificacoes_browser.cjs: central responsiva, persistência, deep link, contador e permissão bloqueada.
A suíte atual de agenda/equipe/PWA/cliente público/fotos/temas/caixa/mensalistas continua executando.
Envio em aparelhos físicos e comportamento do sistema operacional precisam ser validados com credenciais reais e permissão no aparelho.
