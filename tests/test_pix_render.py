"""Confere que o SVG do navegador preserva exatamente o PIX oficial de teste."""
import json
from pathlib import Path
import cv2
folder=Path('test-results')
expected=json.loads((folder/'pix-qr-fixture.json').read_text(encoding='utf-8'))['payload']
image=cv2.imread(str(folder/'pix-qr-renderizado.png'))
assert image is not None,'Captura do QR não encontrada'
decoded,_,_=cv2.QRCodeDetector().detectAndDecode(image)
assert decoded==expected,'QR exibido não corresponde ao código PIX oficial'
print('OK QR PIX renderizado no navegador decodificado sem alteração do payload.')
