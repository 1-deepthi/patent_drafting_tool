from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from app.core.config import settings
from app.core.firebase import initialize_firebase
from app.api.auth import router as auth_router
from app.api.resources import router as resources_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Keep startup usable before credentials are configured; /health reports setup status.
    try:
        initialize_firebase()
        app.state.firebase_ready = True
    except Exception as exc:
        app.state.firebase_ready = False
        app.state.firebase_error = str(exc)
    yield

app = FastAPI(title=settings.app_name, version='1.0.0', description='Firebase-backed Patent Platform API', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.cors_origins.split(',') if x.strip()], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=[x.strip() for x in settings.allowed_hosts.split(',') if x.strip()] or ['*'])

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    detail = 'Internal server error' if settings.environment == 'production' else f'{type(exc).__name__}: {exc}'
    return JSONResponse(status_code=500, content={'detail': detail})

@app.get('/', tags=['health'])
def root():
    return {'name': settings.app_name, 'version': '1.0.0', 'docs': '/docs', 'health': '/health'}

@app.get('/health', tags=['health'])
def health(request: Request):
    try:
        from app.core.firebase import db
        db().collection('_health').limit(1).get()
        return {'status': 'ok', 'firebase': 'connected', 'environment': settings.environment}
    except Exception as exc:
        return JSONResponse(status_code=503, content={'status': 'degraded', 'firebase': 'not_configured_or_unreachable', 'detail': str(exc) if settings.environment != 'production' else 'Firebase unavailable', 'environment': settings.environment})

app.include_router(auth_router, prefix='/api/auth', tags=['Authentication'])
app.include_router(resources_router, prefix='/api', tags=['Patent Platform'])
