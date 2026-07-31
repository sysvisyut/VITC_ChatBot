import httpx
import json

def test_stream_endpoint():
    url = "http://localhost:8003/stream/"
    headers = {
        "X-API-Key": "dev_key_123",
        "Content-Type": "application/json"
    }
    payload = {"query": "What are the hostel rules?"}
    
    print("Sending request to /stream/...")
    try:
        with httpx.stream("POST", url, headers=headers, json=payload, timeout=30.0) as response:
            if response.status_code != 200:
                print(f"Failed with status code: {response.status_code}")
                print(response.read().decode())
                return

            print(f"Response Content-Type: {response.headers.get('content-type')}")
            assert "text/event-stream" in response.headers.get("content-type", "")

            print("Receiving chunks:")
            for line in response.iter_lines():
                if line:
                    print(line)
                    if line.startswith("data: "):
                        data = json.loads(line[6:])
                        if data.get("type") == "metadata":
                            print("Received final metadata successfully!")
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    test_stream_endpoint()
