"""Mantém compatibilidade com o comando de inicialização do projeto original."""
import os
from app import app

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0' if os.environ.get('RENDER') else '127.0.0.1', port=int(os.environ.get('PORT', '8000')))
