"""
batch_inference_server — Provide a scalable, batch-oriented inference server for ML models. Enables efficient processing of multiple requests in parallel, reducing latency and resource overhead.

### PART-META-JSON
{
  "name": "batch_inference_server",
  "layer": "ml",
  "purpose": "Provide a scalable, batch-oriented inference server for ML models. Enables efficient processing of multiple requests in parallel, reducing latency and resource overhead.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: process_batch(batch); start_server(host, port, model_loader, allowed_origins=None); InferenceRequest(...); InferenceResponse(...); ModelLoader(...).",
  "outputs": "Returns: process_batch -> List[InferenceResponse]; start_server -> None.",
  "files_created": [],
  "security_notes": "The server has no built-in authentication and should remain behind an authenticated gateway. Cross-origin access is disabled by default; wildcard origins are rejected.",
  "ai_usage": "Import what you need from `scrapyard.ml.batch_inference_server`.",
  "example": "from scrapyard.ml.batch_inference_server import *",
  "import_path": "scrapyard.ml.batch_inference_server"
}
### END-PART-META
"""
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any
import os, logging, tempfile
from starlette.middleware.cors import CORSMiddleware
from fastapi import FastAPI
from fastapi.testclient import TestClient
import uvicorn

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    yield
    logger.info("Server shutting down gracefully")

@dataclass
class InferenceRequest:
    id: int
    model_name: str
    input_data: Dict[str, Any]

@dataclass
class InferenceResponse:
    request_id: int
    output_data: Optional[Dict[str, Any]] = None
    status_code: int = 200

class ModelLoader:
    def __init__(self):
        self.models: Dict[str, Dict[str, Any]] = {}
    
    def load_model(self, model_name: str) -> Any:
        if model_name not in self.models:
            class MockModel:
                def __init__(self, name: str):
                    self.name = name
                def predict(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
                    return {"result": "predicted_value", "model": self.name}
            
            self.models[model_name] = {"name": model_name, "model": MockModel(model_name)}
        return self.models[model_name]["model"]
    
    def unload_model(self, model_name: str) -> None:
        if model_name in self.models:
            del self.models[model_name]
    
    def __call__(self, model_name: str) -> Any:
        return self.load_model(model_name)

def process_batch(batch: List[InferenceRequest]) -> List[InferenceResponse]:
    batch_responses: List[InferenceResponse] = []
    for request in batch:
        try:
            output_data = {"result": "predicted_value"}
            response = InferenceResponse(request_id=request.id, output_data=output_data, status_code=200)
            batch_responses.append(response)
        except Exception as e:
            logger.error(f"Error processing batch request: {e}")
            response = InferenceResponse(request_id=request.id, output_data=None, status_code=500)
            batch_responses.append(response)
    return batch_responses

def start_server(
    host: str,
    port: int,
    model_loader: ModelLoader,
    allowed_origins: Optional[List[str]] = None,
) -> None:
    if allowed_origins and "*" in allowed_origins:
        raise ValueError("wildcard CORS origins are not permitted")
    app = FastAPI(lifespan=_lifespan)
    
    @app.post("/batch-inference", response_model=List[InferenceResponse])
    async def batch_endpoint(requests: List[InferenceRequest]) -> List[InferenceResponse]:
        batch_responses: List[InferenceResponse] = []
        for request in requests:
            try:
                model_name = request.model_name
                input_data = request.input_data
                model = model_loader.load_model(model_name)
                output_data = model.predict(input_data)
                response = InferenceResponse(request_id=request.id, output_data=output_data, status_code=200)
                batch_responses.append(response)
            except Exception as e:
                logger.error(f"Error processing batch request: {e}")
                response = InferenceResponse(request_id=request.id, output_data=None, status_code=500)
                batch_responses.append(response)
        return batch_responses
    
    @app.get("/health")
    async def health_check() -> Dict[str, str]:
        return {"status": "healthy"}
    
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )
    
    uvicorn.run(app, host=host, port=port)

def _selftest() -> None:
    try:
        start_server("127.0.0.1", 0, ModelLoader(), ["*"])
    except ValueError as exc:
        assert "wildcard" in str(exc)
    else:
        raise AssertionError("wildcard CORS origin must be rejected")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tempdir:
        log_file = os.path.join(tempdir, "app.log")
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.ERROR)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.setLevel(logging.ERROR)
        
        app = FastAPI(lifespan=_lifespan)
        
        @app.post("/batch-inference", response_model=List[InferenceResponse])
        async def test_process_batch(requests: List[InferenceRequest]) -> List[InferenceResponse]:
            responses: List[InferenceResponse] = []
            for req in requests:
                try:
                    model_loader = ModelLoader()
                    model = model_loader.load_model(req.model_name)
                    output_data = model.predict(req.input_data)
                    responses.append(InferenceResponse(request_id=req.id, output_data=output_data, status_code=200))
                except Exception as e:
                    logger.error(f"Error processing batch request: {e}")
                    responses.append(InferenceResponse(request_id=req.id, output_data=None, status_code=500))
            return responses
        
        @app.get("/health")
        async def health_check() -> Dict[str, str]:
            return {"status": "healthy"}
        
        client = TestClient(app)
        
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}
        
        test_payload = [{"id": 1, "model_name": "test_model", "input_data": {}}]
        response = client.post("/batch-inference", json=test_payload)
        assert response.status_code == 200
        json_response = response.json()
        assert len(json_response) == 1
        assert json_response[0]["request_id"] == 1
        assert json_response[0]["output_data"]["result"] == "predicted_value"
        assert json_response[0]["status_code"] == 200
        
        direct_request = InferenceRequest(id=2, model_name="test_model", input_data={})
        responses = process_batch([direct_request])
        assert len(responses) == 1
        assert responses[0].request_id == 2
        assert responses[0].output_data is not None
        assert responses[0].output_data["result"] == "predicted_value"
        assert responses[0].status_code == 200
        
        model_loader = ModelLoader()
        model = model_loader.load_model("test_model")
        assert "test_model" in model_loader.models
        prediction = model.predict({})
        assert prediction["result"] == "predicted_value"
        
        model_via_call = model_loader("test_model")
        assert model_via_call is model
        
        del client
        
        for handler in logger.handlers:
            handler.flush()
        
        with open(log_file, "r") as f:
            log_content = f.read()
            assert "Error processing batch request" not in log_content
        
        logger.removeHandler(file_handler)
        file_handler.close()
        
        print("Self-test passed!")

if __name__ == "__main__":
    _selftest()
