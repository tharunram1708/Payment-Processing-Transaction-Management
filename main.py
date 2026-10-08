from fastapi import FastAPI

from routes import router


app = FastAPI(
    title="Payment Processing API",
    description="FastAPI service for making payments and managing transactions.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.include_router(router)
