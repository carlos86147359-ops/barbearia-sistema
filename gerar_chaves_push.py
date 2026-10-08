"""Gera credenciais VAPID para guardar somente nas variáveis privadas do Render.
Execute em um terminal privado. Nunca envie a saída ao GitHub ou em mensagens.
"""
import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
if __name__=='__main__':
    key=ec.generate_private_key(ec.SECP256R1())
    enc=lambda b:base64.urlsafe_b64encode(b).decode().rstrip('=')
    print('WEB_PUSH_VAPID_PRIVATE_KEY='+enc(key.private_numbers().private_value.to_bytes(32,'big')))
    print('WEB_PUSH_VAPID_PUBLIC_KEY='+enc(key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)))
    print('WEB_PUSH_VAPID_SUBJECT=mailto:grupohavo061@gmail.com')
