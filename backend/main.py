from fastapi import FastAPI

app = FastAPI(title="TNChatbot API")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/")
def root() -> dict:
    return {"message": "TNChatbot backend is running"}
