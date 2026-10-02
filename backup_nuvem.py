"""Backup PostgreSQL criptografado com ensaio em banco temporário."""
import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from recursos import TABLES

AAD=b'barbersaas-backup-encrypted-v1'
def cifrar(raw,public_pem):
    public=serialization.load_pem_public_key(public_pem)
    if not isinstance(public,rsa.RSAPublicKey) or public.key_size<3072:raise ValueError('Chave pública inválida.')
    key=AESGCM.generate_key(bit_length=256);nonce=secrets.token_bytes(12)
    wrapped=public.encrypt(key,padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=AAD))
    enc=lambda v:base64.b64encode(v).decode('ascii')
    return json.dumps({'formato':'barbersaas-cifrado','versao':1,'chave':enc(wrapped),'nonce':enc(nonce),'dados':enc(AESGCM(key).encrypt(nonce,raw,AAD))}).encode()

def decifrar(raw,private_pem):
    data=json.loads(raw)
    if data.get('formato')!='barbersaas-cifrado' or data.get('versao')!=1:raise ValueError('Formato inválido.')
    private=serialization.load_pem_private_key(private_pem,password=None)
    dec=lambda v:base64.b64decode(v,validate=True)
    key=private.decrypt(dec(data['chave']),padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=AAD))
    return AESGCM(key).decrypt(dec(data['nonce']),dec(data['dados']),AAD)

def gravar_novo(path,raw):
    with Path(path).open('xb') as f:f.write(raw)

def exportar(dsn):
    import psycopg
    from psycopg.rows import dict_row
    # Não importa app.py nem inicia migrações no banco de origem.
    with psycopg.connect(dsn,connect_timeout=20,row_factory=dict_row) as db:
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        db.execute("SET LOCAL statement_timeout='60s'")
        tables={table:[dict(row) for row in db.execute('SELECT '+','.join(columns)+' FROM '+table)] for table,columns in TABLES.items()}
    return {'formato':'barbersaas-backup','versao':1,'criado_em':datetime.now(timezone.utc).isoformat(),'tabelas':tables}

def executar(output,public_path,dsn,test_dsn):
    from restaurar_backup import ler,restaurar
    if not dsn or not test_dsn or test_dsn==dsn:raise ValueError('Conexões ausentes ou iguais.')
    # O destino só pode ser o PostgreSQL descartável do executor, nunca a nuvem.
    from urllib.parse import urlparse
    if urlparse(test_dsn).hostname not in ('localhost','127.0.0.1'):raise ValueError('Destino deve ser local e temporário.')
    raw=json.dumps(exportar(dsn),ensure_ascii=False).encode()
    with tempfile.TemporaryDirectory() as tmp:
        plain=Path(tmp)/'backup.json';plain.write_bytes(raw)
        tables=ler(plain,hashlib.sha256(raw).hexdigest())
        previous=os.environ.get('RESTORE_DATABASE_URL')
        try:
            os.environ['RESTORE_DATABASE_URL']=test_dsn
            restaurar(tables,postgres=True)  # Recusa banco com tabelas.
        finally:
            if previous is None:os.environ.pop('RESTORE_DATABASE_URL',None)
            else:os.environ['RESTORE_DATABASE_URL']=previous
    sealed=cifrar(raw,Path(public_path).read_bytes())
    target=Path(output);target.mkdir(parents=True,exist_ok=True)
    name='backup-barbersaas-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'.cifrado.json'
    gravar_novo(target/name,sealed)
    gravar_novo(target/(name+'.sha256'),hashlib.sha256(sealed).hexdigest().encode())
    print('Cópia criptografada e restauração em PostgreSQL temporário validadas.')

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='acao',required=True)
    k=sub.add_parser('chaves');k.add_argument('privada');k.add_argument('publica')
    d=sub.add_parser('abrir');d.add_argument('arquivo');d.add_argument('privada');d.add_argument('saida')
    b=sub.add_parser('executar');b.add_argument('--saida',default='backup-cifrado');b.add_argument('--publica',default='backup-publica.pem')
    args=p.parse_args()
    try:
        if args.acao=='chaves':
            if Path(args.privada).exists() or Path(args.publica).exists():raise ValueError('Recusa sobrescrever chaves.')
            private=rsa.generate_private_key(public_exponent=65537,key_size=3072)
            gravar_novo(args.privada,private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
            gravar_novo(args.publica,private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
            print('Par criado. Guarde a chave privada fora do GitHub.')
        elif args.acao=='abrir':
            raw=decifrar(Path(args.arquivo).read_bytes(),Path(args.privada).read_bytes())
            gravar_novo(args.saida,raw);print('Cópia aberta em arquivo novo.')
        else:executar(args.saida,args.publica,os.environ.get('BACKUP_DATABASE_URL'),os.environ.get('BACKUP_TEST_DATABASE_URL'))
    except Exception:
        # Nunca imprime exceções de conexão, que podem conter segredos.
        print('Operação interrompida. Confira conexão, chave e destino vazio. Não foi publicado um backup válido por esta execução.',file=sys.stderr)
        return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
