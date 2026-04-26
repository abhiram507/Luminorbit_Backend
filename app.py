from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def root():
    return {"status": "Luminorbit wrapper running"}

@app.get("/health")
def health():
    return {"status": "ok"}

# Lazy-load your backend safely
real_app = None

def get_real_app():
    global real_app
    if real_app is None:
        import luminorbit_backend
        real_app = getattr(luminorbit_backend, "app", None)
    return real_app

@app.api_route("/{path:path}", methods=["GET","POST","PUT","DELETE"])
async def catch_all(path: str):
    try:
        backend = get_real_app()
        if backend:
            return {"status": "backend loaded", "path": path}
        else:
            return {"error": "Backend app not found"}
    except Exception as e:
        return {"error": str(e)}
