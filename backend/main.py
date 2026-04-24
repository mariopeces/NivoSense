from pathlib import Path

import yaml
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="NivoSense API", version="0.1.0")

# Demo pública durante el hackathon: CORS abierto.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

LAYERS_FILE = Path(__file__).parent / "layers.yaml"
with LAYERS_FILE.open("r", encoding="utf-8") as f:
    LAYERS: dict = yaml.safe_load(f).get("layers", {})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/layers")
def list_layers():
    return [
        {"id": key, "label": meta.get("label", key), "path": meta.get("path")}
        for key, meta in LAYERS.items()
    ]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
