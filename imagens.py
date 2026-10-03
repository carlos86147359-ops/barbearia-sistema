"""Logo/capa públicos no Cloudinary; arquivos nunca são gravados no Render ou Neon."""
import base64
import io
import json
import os
import re
import secrets
import urllib.request
import warnings
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD=600_000
LIMITS={'logo':(512,120_000),'capa':(1200,250_000)}

def pronto():
    return bool(re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',os.environ.get('CLOUDINARY_CLOUD_NAME','')) and os.environ.get('CLOUDINARY_API_KEY') and os.environ.get('CLOUDINARY_API_SECRET'))

def preparar(raw,kind):
    if not raw or len(raw)>MAX_UPLOAD: raise HTTPException(413,'A imagem é grande demais. Escolha uma imagem menor.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as original:
                if original.format not in ('JPEG','PNG','WEBP') or original.width*original.height>4_000_000 or getattr(original,'n_frames',1)>1:
                    raise HTTPException(422,'Escolha uma foto JPG, PNG ou WebP sem animação.')
                image=ImageOps.exif_transpose(original).convert('RGBA')
                edge,limit=LIMITS[kind]
                image.thumbnail((edge,edge),Image.Resampling.LANCZOS)
                for quality in (80,65,50):
                    out=io.BytesIO();image.save(out,format='WEBP',quality=quality,method=4)
                    if out.tell()<=limit:return out.getvalue()
        raise HTTPException(413,'Não conseguimos reduzir a imagem. Escolha outra foto.')
    except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombWarning,Image.DecompressionBombError):
        raise HTTPException(422,'Não conseguimos abrir esta imagem. Use JPG, PNG ou WebP.')

def enviar(raw,shop_id,kind):
    cloud=os.environ['CLOUDINARY_CLOUD_NAME']
    public_id='barbersaas/'+shop_id+'/'+kind
    boundary='barber-'+secrets.token_hex(16)
    chunks=[]
    for key,value in {'public_id':public_id,'overwrite':'true','invalidate':'true','backup':'false','format':'webp'}.items():
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    chunks.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{kind}.webp"\r\nContent-Type: image/webp\r\n\r\n'.encode(),raw,f'\r\n--{boundary}--\r\n'.encode()])
    credentials=(os.environ['CLOUDINARY_API_KEY']+':'+os.environ['CLOUDINARY_API_SECRET']).encode()
    req=urllib.request.Request(f'https://api.cloudinary.com/v1_1/{cloud}/image/upload',data=b''.join(chunks),headers={'Content-Type':'multipart/form-data; boundary='+boundary,'Authorization':'Basic '+base64.b64encode(credentials).decode()},method='POST')
    try:
        with urllib.request.urlopen(req,timeout=30) as response:data=json.loads(response.read(64_000))
        url=data.get('secure_url','');parsed=urlsplit(url)
        if data.get('public_id')!=public_id or parsed.scheme!='https' or parsed.hostname!='res.cloudinary.com' or not parsed.path.startswith('/'+cloud+'/image/upload/'):
            raise ValueError('Resposta inválida')
        return url
    except Exception:
        # Não revelar resposta do provedor, credenciais nem detalhes internos.
        raise HTTPException(502,'Não foi possível salvar a imagem na nuvem. Tente novamente em instantes.')

def instalar(app,core):
    @app.get('/api/imagens/status')
    def status(request:Request):
        with core['banco']() as db:core['dono'](request,db)
        return {'disponivel':pronto()}

    @app.post('/api/imagens/{kind}')
    async def upload(kind:str,request:Request):
        if kind not in LIMITS:raise HTTPException(404,'Imagem não encontrada.')
        with core['banco']() as db:user=core['dono'](request,db,True)
        if not pronto():raise HTTPException(503,'O envio de imagens aguarda a configuração do armazenamento.')
        core['limitar'](request,'imagens-'+user['loja_id'],12,3600)
        chunks=[];total=0
        async for chunk in request.stream():
            total+=len(chunk)
            if total>MAX_UPLOAD:raise HTTPException(413,'A imagem é grande demais. Escolha uma imagem menor.')
            chunks.append(chunk)
        processed=await run_in_threadpool(preparar,b''.join(chunks),kind)
        url=await run_in_threadpool(enviar,processed,user['loja_id'],kind)
        def persistir():
            with core['banco']() as db:
                if core['DATABASE_URL']:db.execute('SELECT pg_advisory_xact_lock(?)',(7821601,))
                else:db.execute('BEGIN IMMEDIATE')
                # Revalidar a sessão caso tenha sido revogada durante o envio.
                current=core['dono'](request,db,True)
                cfg=core['config_da_loja'](db,current['loja_id']);cfg[kind+'_url']=url
                db.execute('UPDATE lojas SET configuracao=? WHERE id=?',(json.dumps(cfg),current['loja_id']))
        await run_in_threadpool(persistir)
        return {'url':url,'bytes':len(processed)}
