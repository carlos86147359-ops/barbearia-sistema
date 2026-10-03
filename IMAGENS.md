# Imagens da barbearia

O dono abre **Barbearia → Identidade visual e contatos públicos** e escolhe **Enviar logo** ou **Enviar foto de capa**. Após conferir a prévia, usa **Salvar logo/capa**. Cada imagem é salva imediatamente, sem alterar outros campos ainda não salvos. Remover limpa a prévia; aplicar com **Salvar configurações**. Links HTTPS existentes continuam aceitos como alternativa.

## Ativação no Render

Criar uma conta Cloudinary Image & Video API no plano gratuito. Não contratar upgrade. Em Settings → API Keys, localizar Cloud name, API Key e API Secret. Cadastrar diretamente em Environment do serviço Render:

- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`

Salvar e aguardar novo deploy. Não enviar chaves pelo chat, não colocá-las no GitHub ou em código do frontend. O status de integração informa apenas se as três variáveis estão presentes; o primeiro envio verifica de fato as credenciais e limites do provedor.

## Limites e funcionamento

- Galeria: JPG, PNG ou WebP, até 15 MB na origem e 50 milhões de pixels; outros formatos precisam ser convertidos antes.
- Dispositivo: reduz mantendo proporção; logo até 512 px/120 KB e capa até 1200 px/250 KB. WebP quando suportado.
- Servidor: recebe até 600 KB por stream, autentica dono e CSRF antes do processamento, valida decodificação/formato/dimensões/animação, remove metadados e recomprime em WebP. Máximo de 12 tentativas por loja/IP/hora.
- Upload HTTPS autenticado no servidor. Os public IDs são `barbersaas/{loja_id}/logo` e `.../capa`; não são escolhidos pelo cliente. Substituições reaproveitam esses IDs, usando URL versionada para atualização da imagem.
- Bytes ficam no Cloudinary, não em disco temporário do Render, repositório ou banco Neon. O JSON da loja contém apenas a URL. Nenhum SDK adicional; Pillow só processa envios, não reservas.
- Remoção da página não exclui o arquivo do provedor; mantém a última imagem de cada tipo até substituição ou limpeza manual pelo administrador. Backups do banco guardam URLs, não cópias dos bytes. As imagens originais devem ser preservadas pelo estabelecimento. Versões antigas podem deixar de estar disponíveis após substituição.
- O plano gratuito tem limites de armazenamento, entrega e processamento. Acompanhar uso no Cloudinary antes de crescer; não há promessa de gratuidade ilimitada.

Referências: https://cloudinary.com/documentation/image_upload_api_reference e https://cloudinary.com/documentation/billing_and_plans.
