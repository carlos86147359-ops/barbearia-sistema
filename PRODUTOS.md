# Produtos e Caixa — fase 1

## Estrutura e implantação
O núcleo existente é FastAPI, PostgreSQL/SQLite e HTML/CSS/JavaScript, com autenticação por cookie e proteção CSRF. O novo módulo fica em produtos.py e em uma página própria /produtos, reutilizando o design system e as sessões. A agenda e o agendamento público permanecem separados.

Foram adicionadas seis tabelas: produtos, variantes_produto, permissoes_caixa, vendas_produtos, itens_venda e movimentacoes_estoque. Migração aditiva, sem apagar dados existentes. Índices por loja, vendedor e data; chaves compostas impedem relações entre lojas. Todo produto tem pelo menos uma variante, mesmo sem atributos.

Valores em centavos inteiros. Venda guarda nome, atributos, preço e custo por item. Desconto distribuído entre os itens, com soma exata. Alterações futuras não recalculam o histórico. Lucro apresentado é bruto, sem impostos, despesas ou comissões.

Vendas e estoque usam uma transação com bloqueio por loja no PostgreSQL e BEGIN IMMEDIATE no SQLite. O estoque é validado novamente dentro da transação. Chave de idempotência evita duplicação por repetição do pedido. Total esperado detecta alteração de preços durante a revisão. Cancelamento exige motivo, preserva o registro e pode devolver estoque uma única vez; correção cancela e prepara nova venda para revisão.

## Acesso
Dono: catálogo, vendas de toda a loja, estoque, movimentos, indicadores e permissões.
Profissional: acesso negado inicialmente; flags individuais controlam PDV, vendas, estoque, custos, lucro, movimentação, cancelamento das próprias vendas e desconto. Lucro requer permissão de custo. A API remove custos e lucros sem autorização. Todas as rotas de dados exigem sessão; operações exigem CSRF e validação da loja. Produtos não entram na página pública.

Na aba Permissões, o dono autoriza contas ativas criadas por convite na Equipe. Produto inativo sai das opções de venda; estoque e histórico permanecem.

## Recuperação
Backups manuais e automáticos incluem as seis tabelas. Restauração usa os mesmos tipos, restrições e índices do módulo. Cópias anteriores sem o módulo são aceitas, criando as tabelas novas vazias. Cópia com somente parte das tabelas novas é rejeitada. Restauração continua permitida somente em destino novo/vazio.

## Validação
Testes cobrem estoque concorrente, repetição da venda, snapshots, mudança de preço, cancelamento único, isolamento entre lojas, permissões sem vazamento de custos e recuperação de backup antigo/novo. O ensaio PostgreSQL no GitHub restaura produtos/vendas e testa duas vendas concorrentes para a última unidade. A interface possui testes de centavos, desconto e atributos, além da revisão visual.

## Próxima fase
Abertura/fechamento de caixa, sangria, suprimentos de caixa, fornecedores, compras detalhadas, relatórios avançados, ranking e comissões sobre produtos ficam para uma fase futura. O custo informado na reposição passa a ser o custo padrão daquela variante para vendas seguintes; vendas anteriores usam seu snapshot. Não há custo médio ponderado nesta fase. Imagens de produtos são cadastradas por link HTTPS.
