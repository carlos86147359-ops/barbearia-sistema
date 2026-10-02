import importlib.util
import json
import tempfile
from pathlib import Path
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('backup_cloud',ROOT/'backup_nuvem.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
private=rsa.generate_private_key(public_exponent=65537,key_size=3072)
pub=private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
pem=private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
raw=b'{"cliente":"CLIENTE-PRIVADO","telefone":"11999999999"}'
sealed=m.cifrar(raw,pub)
assert b'CLIENTE-PRIVADO' not in sealed and b'11999999999' not in sealed
assert m.decifrar(sealed,pem)==raw
data=json.loads(sealed);data['dados']=data['dados'][:-4]+'AAAA'
try:m.decifrar(json.dumps(data).encode(),pem);raise AssertionError('Aceitou adulteracao')
except InvalidTag:pass
other=rsa.generate_private_key(public_exponent=65537,key_size=3072)
wrong=other.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
try:m.decifrar(sealed,wrong);raise AssertionError('Aceitou chave errada')
except ValueError:pass
with tempfile.TemporaryDirectory() as tmp:
    path=Path(tmp)/'arquivo';m.gravar_novo(path,raw)
    try:m.gravar_novo(path,b'x');raise AssertionError('Sobrescreveu arquivo')
    except FileExistsError:pass
try:m.executar('unused','unused','origem','postgresql://user:pass@neon.example/test');raise AssertionError('Aceitou destino remoto')
except ValueError:pass
print('OK: criptografia, integridade, chave errada, destino isolado e arquivos preservados.')
