
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

import resualign.api as api_module

router = APIRouter()

@router.get('/', response_class=HTMLResponse)
def index():
    """Serve the frontend HTML."""
    if not api_module._static_dir.is_dir():
        return HTMLResponse('<h1>ResuAlign API</h1><p>Frontend not available.</p>')
    return HTMLResponse((api_module._static_dir / 'index.html').read_text(encoding='utf-8'))

@router.get('/health')
def health():
    """Liveness probe."""
    return {'status': 'ok'}

