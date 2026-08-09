"""
http_client — Reusable HTTP client for CLI tools: make_request/HttpClient wrap common request patterns with typed responses and error handling.

### PART-META-JSON
{
  "name": "http_client",
  "layer": "clitools",
  "purpose": "Reusable HTTP client for CLI tools: make_request/HttpClient wrap common request patterns with typed responses and error handling.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: make_request(method, url, params, headers, data, json, timeout, auth); HttpClient(...).",
  "outputs": "Returns: make_request -> requests.Response.",
  "files_created": [],
  "security_notes": "Makes outbound network calls; set timeouts, validate URLs/hosts, and never send secrets to untrusted endpoints.",
  "ai_usage": "Import what you need from `scrapyard.clitools.http_client`.",
  "example": "from scrapyard.clitools.http_client import *",
  "import_path": "scrapyard.clitools.http_client"
}
### END-PART-META
"""
from typing import Optional, Dict, Any, Tuple
import requests
import logging

# Setup logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

class HttpClient:
    def __init__(self, base_url: str, timeout: int = 10):
        self.base_url = base_url
        self.timeout = timeout
        self.session = requests.Session()

    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}{path}"
        headers = kwargs.pop("headers", {})
        data = kwargs.pop("data", None)
        json_data = kwargs.pop("json", None)
        params = kwargs.pop("params", {})
        auth = kwargs.pop("auth", None)

        try:
            response = self.session.request(
                method=method,
                url=url,
                headers=headers,
                data=data,
                json=json_data,
                params=params,
                timeout=self.timeout,
                auth=auth,
                **kwargs
            )
            response.raise_for_status()
            logger.debug(f"Request to {url} successful. Status code: {response.status_code}")
            return response
        except requests.RequestException as e:
            logger.error(f"HTTP request failed: {e}")
            raise

def make_request(
    method: str,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    data: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
    timeout: Optional[int] = None,
    auth: Optional[Tuple[str, str]] = None
) -> requests.Response:
    try:
        response = requests.request(
            method=method,
            url=url,
            params=params,
            headers=headers,
            data=data,
            json=json,
            timeout=timeout or 10,
            auth=auth
        )
        response.raise_for_status()
        logger.debug(f"Request to {url} successful. Status code: {response.status_code}")
        return response
    except requests.RequestException as e:
        logger.error(f"HTTP request failed: {e}")
        raise

def _selftest():
    # Test make_request function
    try:
        response = make_request("GET", "https://httpbin.org/get")
        assert response.status_code == 200
        print("make_request test passed.")
    except Exception as e:
        print(f"make_request test failed: {e}")

    # Test HttpClient class
    client = HttpClient(base_url="https://httpbin.org/")
    try:
        response = client.request("GET", "/get")
        assert response.status_code == 200
        print("HttpClient request test passed.")
    except Exception as e:
        print(f"HttpClient request test failed: {e}")

if __name__ == "__main__":
    _selftest()
