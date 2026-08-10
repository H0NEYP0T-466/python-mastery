# Inference Serving Patterns

## What it is
Serving ML models through an API means more than just wrapping model.predict() in a POST endpoint. Production inference serving involves batching, model loading strategies, async inference, GPU sharing, model versioning, A/B testing, cold start mitigation, and cost optimization. This file covers the patterns used by real ML serving systems (TorchServe, Triton, vLLM, TGI) and how to implement them in FastAPI, grounded in practical ML serving experience.

## Why it matters
If you've trained a model (GPT-2 on WhatsApp data, DINOv2 fine-tuning), you know that training is only half the battle. Serving is where the model meets users — and where most ML projects fail in production. A poorly served model wastes GPU, has high latency, can't scale, and costs more than it should. In interviews, ML system design questions test whether you understand batching, model loading, GPU utilization, and the trade-offs between latency and throughput. For your work — serving your own models — this is the difference between a demo and a production service.

## Core example

### The serving architecture — layers

```python
# A production ML serving system has multiple layers:

# Layer 1: API Gateway (FastAPI)
# - Auth, rate limiting, request validation
# - Request routing (which model version)
# - Response formatting
# - Caching (for repeated inputs)

# Layer 2: Inference Scheduler
# - Batching (group multiple requests)
# - Queue management (prioritization)
# - Load balancing (across model instances)
# - Dynamic batching (wait for more requests)

# Layer 3: Model Executor
# - Model loading (GPU/CPU)
# - Inference execution (batched)
# - Post-processing
# - Memory management (GPU memory)

# Layer 4: Model Registry
# - Model versioning
# - Model storage (S3, local, HF Hub)
# - Model metadata (accuracy, latency, input schema)
# - A/B testing configuration

# Each layer can be scaled independently. The API gateway scales
# with request rate. The model executor scales with compute needs.
# The model registry is shared across all instances.
```

### Model loading strategies — the cold start problem

```python
# Problem: loading a 5GB model takes 30-60 seconds. During this
# time, the API can't serve requests. This is the "cold start."

# Strategy 1: Pre-load on startup (eager loading)
# Load the model when the API starts, not on first request.

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load all models on startup
    await model_registry.load_all()
    # Or load specific models based on configuration
    await model_registry.load("dinov2-v1")
    await model_registry.load("gpt2-whatsapp")
    yield
    # Unload on shutdown
    await model_registry.unload_all()

app = FastAPI(lifespan=lifespan)

# Pros: no cold start on first request
# Cons: slow startup, loads all models even if not needed,
#       high memory usage from the start
# Best for: production with known model set, sufficient memory

# Strategy 2: Lazy loading with caching
# Load on first request, keep in memory for subsequent requests.

class ModelLoader:
    def __init__(self):
        self.models: dict[str, Any] = {}
        self._locks: dict[str, asyncio.Lock] = {}
    
    async def get_model(self, name: str) -> Any:
        if name not in self.models:
            # Double-checked locking to prevent race condition
            # (multiple requests trying to load the same model)
            if name not in self._locks:
                self._locks[name] = asyncio.Lock()
            
            async with self._locks[name]:
                # Check again after acquiring lock
                if name not in self.models:
                    self.models[name] = await self._load_model(name)
        
        return self.models[name]
    
    async def _load_model(self, name: str) -> Any:
        logger.info(f"Loading model {name}...")
        start = time.time()
        model = await load_from_registry(name)
        logger.info(f"Model {name} loaded in {time.time()-start:.1f}s")
        return model

# Pros: fast startup, only loads needed models
# Cons: first request is slow (cold start), race condition risk
# Best for: development, APIs with many models, memory-constrained

# Strategy 3: Warm-up requests
# After loading, send dummy requests to "warm up" the model
# (CUDA graphs, kernel compilation, cache priming).

async def warmup_model(model: Any, num_warmup: int = 10):
    """Send warm-up requests to optimize inference"""
    dummy_input = create_dummy_input()
    for _ in range(num_warmup):
        # Run inference (discard result)
        _ = model(dummy_input)
    
    # For CUDA: synchronize to ensure all kernels are compiled
    if torch.cuda.is_available():
        torch.cuda.synchronize()

# In lifespan:
@asynccontextmanager
async def lifespan(app: FastAPI):
    model = await model_registry.load("dinov2")
    await warmup_model(model, num_warmup=20)
    # Now the model is ready for production traffic
    yield

# Pros: eliminates first-request latency spike, CUDA graphs optimized
# Cons: adds startup time, warm-up input may not match real distribution
# Best for: GPU models, models with compilation overhead (TensorRT, TorchScript)

# Strategy 4: Model pre-fetching
# Predict which models will be needed and load them before requests arrive.
# Based on: time of day, user patterns, scheduled jobs.

async def prefetch_models():
    """Pre-load models based on predicted usage"""
    # Example: load the chat model during business hours,
    # the analytics model during off-hours
    hour = datetime.utcnow().hour
    if 9 <= hour < 18:
        await model_registry.load("chat-model")
    else:
        await model_registry.load("analytics-model")

# Pros: proactive, reduces cold starts for predicted traffic
# Cons: prediction may be wrong, wastes memory if wrong
# Best for: predictable traffic patterns, scheduled workloads

# Recommendation: eager loading + warm-up for production.
# Lazy loading for development or APIs with many rarely-used models.
# Pre-fetching for predictable traffic patterns.
```

### Batching — the single most important optimization

```python
# Batching: process multiple inference requests together in a single
# GPU call. This dramatically improves throughput (requests/second)
# at the cost of slightly higher latency (waiting for the batch).

# Static batching: wait until batch is full, then process
# Dynamic batching: process when batch is full OR timeout expires

class BatchScheduler:
    def __init__(self, max_batch_size: int = 32, batch_timeout: float = 0.1):
        self.max_batch_size = max_batch_size
        self.batch_timeout = batch_timeout
        self.queue: asyncio.Queue = asyncio.Queue()
        self.running = False
    
    async def start(self):
        """Start the batch processing loop"""
        self.running = True
        asyncio.create_task(self._process_batches())
    
    async def stop(self):
        """Stop the batch processing loop"""
        self.running = False
    
    async def submit(self, request: dict) -> Any:
        """Submit a request for batched processing"""
        future = asyncio.Future()
        await self.queue.put((request, future))
        return future  # Caller awaits this for the result
    
    async def _process_batches(self):
        while self.running:
            # Collect requests for the batch
            batch = []
            futures = []
            
            # Get first request (blocks if queue is empty)
            request, future = await self.queue.get()
            batch.append(request)
            futures.append(future)
            
            # Collect more requests until batch is full or timeout
            try:
                while len(batch) < self.max_batch_size:
                    request, future = await asyncio.wait_for(
                        self.queue.get(),
                        timeout=self.batch_timeout
                    )
                    batch.append(request)
                    futures.append(future)
            except asyncio.TimeoutError:
                # Timeout — process what we have
                pass
            
            # Run batched inference
            try:
                results = await self._run_inference(batch)
                
                # Resolve each future with its result
                for result, future in zip(results, futures):
                    if not future.done():
                        future.set_result(result)
            except Exception as e:
                # Set exception on all futures
                for future in futures:
                    if not future.done():
                        future.set_exception(e)
    
    async def _run_inference(self, batch: list[dict]) -> list[Any]:
        """Run batched inference on the model"""
        # Preprocess batch together
        inputs = await self.preprocess_batch(batch)
        
        # Run model on batch (single GPU call)
        outputs = await self.model.infer_batch(inputs)
        
        # Postprocess each output individually
        results = [self.postprocess(out) for out in outputs]
        
        return results

# Usage in endpoint:
batch_scheduler = BatchScheduler(max_batch_size=16, batch_timeout=0.05)

@app.on_event("startup")
async def startup():
    await model.load()
    await batch_scheduler.start()

@app.on_event("shutdown")
async def shutdown():
    await batch_scheduler.stop()

@app.post("/predict/")
async def predict(request: Request):
    body = await request.json()
    
    # Submit to batch scheduler — returns a future
    result = await batch_scheduler.submit(body)
    
    return {"result": result}

# Batching trade-offs:
# - Larger batch size → higher throughput, higher latency
# - Smaller batch size → lower throughput, lower latency
# - Longer timeout → larger batches, higher latency
# - Shorter timeout → smaller batches, lower latency
# 
# For real-time serving: batch_size=4-16, timeout=10-50ms
# For batch processing: batch_size=32-128, timeout=100-500ms
# 
# The optimal batch size depends on the model and GPU.
# Profile: measure throughput and latency at different batch sizes.
# Choose the batch size that gives acceptable latency with max throughput.
```

### GPU memory management — the constant battle

```python
# GPU memory is limited (8GB, 16GB, 24GB, 48GB, 80GB).
# A single model may use 2-20GB. Multiple models or large batches
# can exhaust GPU memory. Managing GPU memory is critical.

# Strategy 1: Single model per GPU
# Load one model per GPU. No sharing. Simple but underutilizes GPU.

# Strategy 2: Model parallelism
# Split a large model across multiple GPUs. Each GPU holds part of the model.
# Requires model architecture support (tensor parallelism, pipeline parallelism).
# Used by: Megatron-LM, DeepSpeed, vLLM.

# Strategy 3: Multi-model serving on one GPU
# Load multiple small models on one GPU. Switch between them.
# Requires careful memory management (unload/load models as needed).

# Strategy 4: Dynamic memory allocation
# Allocate GPU memory as needed. Free when not in use.
# Use torch.cuda.empty_cache() to free unused memory.
# Use memory pools to reduce allocation overhead.

# Strategy 5: Quantization
# Reduce model precision (FP32 → FP16 → INT8 → INT4).
# Reduces memory usage and increases inference speed.
# Trade-off: slight accuracy loss (usually acceptable).

# Quantization levels:
# FP32: 4 bytes per parameter, full precision, slowest
# FP16: 2 bytes per parameter, ~same accuracy, 2x faster (Tensor Cores)
# INT8: 1 byte per parameter, small accuracy loss, 4x smaller, faster
# INT4: 0.5 bytes per parameter, moderate accuracy loss, 8x smaller

# For DINOv2 (ViT): FP16 is standard. No accuracy loss on modern GPUs.
# For GPT-2: INT8 or INT4 with GPTQ/AWQ for production serving.
# Quantization is the single most effective memory optimization.

# GPU memory monitoring:
import torch

def get_gpu_memory():
    """Get GPU memory usage"""
    if not torch.cuda.is_available():
        return 0
    
    allocated = torch.cuda.memory_allocated() / 1024**3  # GB
    reserved = torch.cuda.memory_reserved() / 1024**3  # GB
    
    return {"allocated_gb": allocated, "reserved_gb": reserved}

# Log GPU memory before and after each inference:
logger.info(f"GPU memory before: {get_gpu_memory()}")
output = model(input)
logger.info(f"GPU memory after: {get_gpu_memory()}")

# If memory is growing over time (memory leak):
# - Check for tensors not being freed
# - Use torch.cuda.empty_cache() periodically
# - Use memory profiling (torch.cuda.memory_summary())
# - Avoid keeping references to intermediate tensors
```

### Model versioning and A/B testing

```python
# In production, you need to serve multiple model versions:
# - Current production model (v1)
# - New model being tested (v2)
# - Legacy model for backward compatibility (v0)
# - Canary model for a subset of traffic (v2-canary)

class ModelRegistry:
    def __init__(self):
        self.models: dict[str, Any] = {}  # name → model
        self.routes: dict[str, str] = {}  # endpoint → model name
        self.ab_tests: dict[str, dict] = {}  # test_name → config
    
    def register(self, name: str, model: Any, version: str):
        """Register a new model version"""
        key = f"{name}:{version}"
        self.models[key] = model
        logger.info(f"Registered model {key}")
    
    def route(self, endpoint: str, model_name: str, version: str = "latest"):
        """Route an endpoint to a specific model version"""
        if version == "latest":
            # Find the latest version
            versions = [k for k in self.models if k.startswith(f"{model_name}:")]
            version = max(versions.split(":")[-1]) if versions else "v1"
        self.routes[endpoint] = f"{model_name}:{version}"
    
    def ab_test(self, test_name: str, model_a: str, model_b: str, split: float = 0.5):
        """Set up an A/B test between two models"""
        self.ab_tests[test_name] = {
            "model_a": model_a,
            "model_b": model_b,
            "split": split,  # Fraction of traffic to model_b
            "start_time": datetime.utcnow(),
        }
    
    def get_model(self, endpoint: str, request: dict = None) -> Any:
        """Get the model for a request, considering A/B testing"""
        if endpoint in self.ab_tests:
            test = self.ab_tests[endpoint]
            # Simple random split
            if random.random() < test["split"]:
                model_key = test["model_b"]
            else:
                model_key = test["model_a"]
        elif endpoint in self.routes:
            model_key = self.routes[endpoint]
        else:
            # Default: latest model
            model_key = self._get_latest(endpoint)
        
        return self.models[model_key]

# Usage in endpoint:
registry = ModelRegistry()

# Register models
registry.register("dinov2", model_v1, "v1")
registry.register("dinov2", model_v2, "v2")

# Set up A/B test: 90% traffic to v1, 10% to v2
registry.ab_test("dinov2", "dinov2:v1", "dinov2:v2", split=0.10)

@app.post("/predict/")
async def predict(request: Request):
    body = await request.json()
    
    # Get the model based on routing and A/B testing
    model = registry.get_model("/predict/", body)
    
    # Run inference
    result = await model.infer(body["input"])
    
    # Log which model was used (for A/B test analysis)
    logger.info(
        f"Inference with model={model.version} "
        f"input_hash={hash_input(body['input'])}"
    )
    
    return {"result": result, "model_version": model.version}

# A/B test analysis:
# Compare metrics (accuracy, latency, user engagement) between
# model v1 and v2 traffic. If v2 is significantly better, promote
# it to production (update the route). If v2 is worse, roll back.
# Use statistical significance testing before promoting.
```

### Async inference — not blocking the event loop

```python
# ML inference is typically synchronous (model.predict() blocks).
# In an async FastAPI endpoint, this blocks the event loop.
# Solution: offload inference to a thread or process pool.

import asyncio
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor

# Option 1: Thread pool (for models that release GIL during inference)
# PyTorch models release the GIL during CUDA inference.
thread_pool = ThreadPoolExecutor(max_workers=4)

async def infer_thread(model, input_data):
    loop = asyncio.get_event_loop()
    # Offload to thread pool — event loop is free during inference
    return await loop.run_in_executor(thread_pool, model.predict, input_data)

# Option 2: Process pool (for CPU-bound models or Python GIL-holding code)
process_pool = ProcessPoolExecutor(max_workers=2)

async def infer_process(model, input_data):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(process_pool, model.predict, input_data)

# Option 3: Batch scheduler (from earlier) — best for GPU models
# Multiple requests are batched and processed together.
# The batch scheduler runs in its own async task.
# Requests submit and await their result from the batch.

# Option 4: Separate inference service — best for production
# Run the model in a separate service (TorchServe, Triton, vLLM).
# The FastAPI API calls the inference service via HTTP/gRPC.
# The API is async (non-blocking I/O to the inference service).
# The inference service handles batching, GPU management, scaling.

# Recommendation:
# - Development: thread pool (simplest)
# - Single-model production: batch scheduler (best throughput)
# - Multi-model production: separate inference service (best isolation)
# - Large models: separate inference service with model parallelism

# The key principle: never call model.predict() directly in an
# async endpoint. Always offload (thread, process, batch, or service).
```

### Inference optimization — beyond the model

```python
# Optimization 1: Input preprocessing offloading
# Move preprocessing to CPU (or even client) to free GPU for inference.

async def preprocess_on_cpu(input_data):
    # Run preprocessing on CPU (doesn't need GPU)
    # This frees GPU for the actual inference
    processed = await asyncio.to_thread(preprocess_fn, input_data)
    return processed.to("cuda")  # Move to GPU just before inference

# Optimization 2: Output postprocessing offloading
# Run postprocessing on CPU while GPU starts the next inference.

async def infer_with_offload(model, input_data):
    # Preprocess on CPU
    input_tensor = await asyncio.to_thread(preprocess, input_data)
    input_tensor = input_tensor.to("cuda")
    
    # Inference on GPU
    with torch.no_grad():
        output = model(input_tensor)
    
    # Postprocess on CPU (async, while GPU is free)
    result = await asyncio.to_thread(postprocess, output.cpu())
    
    return result

# Optimization 3: CUDA graphs (NVIDIA-specific)
# Capture the inference execution graph and replay it.
# Reduces CPU overhead (kernel launch, memory allocation).

def create_cuda_graph(model, example_input):
    # Capture the graph
    graph = torch.cuda.CaptureGraph()
    stream = torch.cuda.Stream()
    
    with torch.cuda.stream(stream):
        # Warm-up
        for _ in range(10):
            _ = model(example_input)
        
        # Capture
        graph.capture_begin()
        output = model(example_input)
        graph.capture_end()
    
    return graph, stream

# Replay the graph (much faster than normal execution):
def replay_graph(graph, stream, input_data):
    with torch.cuda.stream(stream):
        graph.replay()
    return output

# Optimization 4: TensorRT (NVIDIA's inference optimizer)
# Convert PyTorch model to TensorRT engine.
# Optimizes layer fusion, precision, memory allocation.
# 2-10x speedup on NVIDIA GPUs.

import torch2trt

def convert_to_tensorrt(model, example_input):
    model_trt = torch2trt.convert(model, [example_input])
    return model_trt

# Inference with TensorRT:
output = model_trt(input_tensor)  # 2-10x faster than PyTorch

# Optimization 5: ONNX Runtime (cross-platform)
# Convert PyTorch model to ONNX format.
# Run with ONNX Runtime (optimized for CPU and GPU).
# Works on non-NVIDIA GPUs and CPUs.

torch.onnx.export(model, example_input, "model.onnx")
session = ort.InferenceSession("model.onnx")
output = session.run(None, {"input": input_numpy})[0]

# Optimization 6: Speculative decoding (for LLMs)
# Use a small "draft" model to propose tokens,
# verify with the large model.
# 2-3x speedup for LLM inference.

# This is what vLLM and TGI use for LLM serving.
# Not applicable for vision models like DINOv2.
```

### Model monitoring and drift detection

```python
# In production, models degrade over time. Input distribution shifts,
# data quality changes, and model accuracy drops. Monitor to detect
# this before users notice.

class ModelMonitor:
    def __init__(self):
        self.input_stats = {}  # Running statistics of inputs
        self.output_stats = {}  # Running statistics of outputs
        self.latency_history = deque(maxlen=1000)  # Recent latencies
        self.error_count = 0
        self.total_count = 0
    
    async def record_inference(self, input_data, output, latency_ms: float, error: bool = None):
        """Record inference metrics for monitoring"""
        self.total_count += 1
        if error:
            self.error_count += 1
        
        # Track latency
        self.latency_history.append(latency_ms)
        
        # Track input statistics (sample to avoid storing everything)
        if random.random() < 0.1:  # Sample 10%
            input_hash = hash_input(input_data)
            self.input_stats[input_hash] = self.input_stats.get(input_hash, 0) + 1
        
        # Track output statistics
        output_key = self._output_key(output)
        self.output_stats[output_key] = self.output_stats.get(output_key, 0) + 1
    
    def check_drift(self) -> dict:
        """Check for input distribution drift"""
        # Compare current input distribution with baseline
        # (baseline should be collected during model validation)
        
        # Simple approach: compare top-K input patterns
        current_top = Counter(self.input_stats).most_common(10)
        baseline_top = self.baseline_top_inputs  # Stored during validation
        
        # Calculate overlap
        current_hashes = set(h for h, _ in current_top)
        baseline_hashes = set(h for h, _ in baseline_top)
        overlap = len(current_hashes & baseline_hashes) / len(baseline_hashes)
        
        return {
            "input_drift_score": 1 - overlap,  # 0 = no drift, 1 = complete drift
            "error_rate": self.error_count / max(self.total_count, 1),
            "p99_latency": sorted(self.latency_history)[int(len(self.latency_history) * 0.99)] if self.latency_history else 0,
        }
    
    def should_alert(self) -> bool:
        """Check if monitoring metrics warrant an alert"""
        drift = self.check_drift()
        
        # Alert conditions:
        if drift["input_drift_score"] > 0.5:
            return True  # Significant input drift
        if drift["error_rate"] > 0.05:
            return True  # Error rate > 5%
        if drift["p99_latency"] > 2 * self.baseline_p99_latency:
            return True  # Latency doubled
        
        return False

# Usage in endpoint:
monitor = ModelMonitor()

@app.post("/predict/")
async def predict(request: Request):
    start = time.perf_counter()
    
    try:
        body = await request.json()
        result = await model.infer(body["input"])
        
        latency_ms = (time.perf_counter() - start) * 1000
        
        # Record for monitoring
        await monitor.record_inference(
            input_data=body["input"],
            output=result,
            latency_ms=latency_ms,
            error=False,
        )
        
        return result
    except Exception as e:
        await monitor.record_inference(
            input_data=body["input"] if 'body' in locals() else None,
            output=None,
            latency_ms=(time.perf_counter() - start) * 1000,
            error=True,
        )
        raise

# Periodically check drift and alert:
async def drift_check_job():
    while True:
        await asyncio.sleep(3600)  # Check every hour
        drift = monitor.check_drift()
        if monitor.should_alert():
            await send_alert(f"Model drift detected: {drift}")
            # Optionally: trigger model retraining or fallback to previous model

# For production: use dedicated monitoring tools
# (Prometheus for metrics, Evidently/WhyLabs for drift detection,
# Grafana for dashboards, Alertmanager for alerts).
```

## Common mistakes / gotchas

- **Loading the model on every request** — the most expensive mistake. Load once, reuse. Use a singleton or dependency with application-level scope.
- **Sync inference in async endpoints** — calling model.predict() directly in an async endpoint blocks the event loop. Always offload (thread, process, batch, or service).
- **Not batching for GPU models** — running inference one request at a time on GPU wastes GPU compute. Batching improves throughput 4-32x. Always batch for GPU models.
- **Ignoring GPU memory leaks** — PyTorch can leak GPU memory if tensors aren't properly freed. Use `torch.cuda.empty_cache()` periodically, avoid keeping references to intermediate tensors, profile memory usage.
- **No model versioning** — deploying a new model without versioning means you can't roll back. Always version models and support multiple versions simultaneously for A/B testing and rollback.
- **Serving CPU models on GPU (or vice versa)** — moving data between CPU and GPU has overhead. If the model is on GPU but preprocessing is on CPU, the data transfer can be the bottleneck. Profile and optimize the data pipeline.
- **Not warming up the model** — the first inference after model loading is slow (CUDA compilation, kernel initialization). Always send warm-up requests before accepting production traffic.
- **No rate limiting on inference endpoints** — inference is expensive. Without rate limiting, a single user can exhaust your GPU budget. Always rate limit inference endpoints, ideally with tier-based limits.
- **Caching non-deterministic results** — if your model has any randomness (temperature > 0, dropout), caching returns different results for the same input. Only cache deterministic inference (temperature=0, eval mode).
- **Not monitoring model performance** — accuracy can drift silently. Without monitoring, you serve a degraded model for weeks. Always track input distribution, output distribution, latency, and error rate.

## Practice

> [!question]- Q1. You trained a DINOv2 model for image classification. The model is 500MB, takes 50ms per inference on A10 GPU, and your API gets 100 requests/second. Design the serving architecture to handle this load with P99 latency under 200ms.
**Answer:** Architecture: (1) **Model loading**: eager load on startup with warm-up (20 dummy requests). Model stays in GPU memory. (2) **Batching**: dynamic batching with max_batch_size=16, timeout=20ms. At 100 req/s, average batch size = 100 × 0.02 = 2 (below max). Throughput: 100 req/s ÷ 2 per batch = 50 batches/s. Each batch takes ~50ms (GPU inference). With batching, effective latency = queue wait (avg 10ms) + inference (50ms) + preprocessing/postprocessing (20ms) = 80ms. Well under 200ms P99. (3) **GPU**: single A10 (24GB) handles the model (500MB) and batch (16 images × ~20MB = 320MB). Total < 1GB GPU memory. (4) **API layer**: FastAPI with async endpoints, offload preprocessing/postprocessing to thread pool. Rate limiting: 200 req/s per user (free tier), 1000 req/s (pro). (5) **Autoscaling**: if latency > 150ms P99, add another replica behind load balancer. Each replica has its own model instance. (6) **Caching**: cache inference results for 1 hour (SHA256 of image → class). If the same image is queried again, return cached result. Expected cache hit rate depends on image diversity. (7) **Monitoring**: track latency (P50, P95, P99), throughput, GPU memory, cache hit rate, error rate. Alert on P99 > 150ms or error rate > 1%. Key design: batching for throughput, single GPU for cost, caching for repeated requests, autoscaling for traffic spikes.

> [!question]- Q2. Your GPT-2 model (124M params, WhatsApp fine-tuned) takes 2 seconds per inference on CPU. Users expect responses under 500ms. You can't upgrade hardware. Design the serving strategy.
**Answer:** Without hardware upgrade, you must optimize the software: (1) **Quantization**: convert from FP32 to INT8 using GPTQ or GGUF. This reduces model size 4x and inference speed 2-4x. Expected inference: 0.5-1 second. (2) **Speculative decoding**: use a smaller draft model (distilled GPT-2, 1/10 the size) to propose tokens, verify with the full model. Speedup: 2-3x. Expected: 0.3-0.7 seconds. (3) **KV cache**: reuse key-value cache for prompt tokens across requests with the same prefix. For chat, cache the conversation history. Speedup: depends on conversation length. (4) **Batching**: if multiple users are generating simultaneously, batch their inference steps. For autoregressive generation, this is tricky (different sequence lengths) but possible with padding and masking. (5) **Streaming**: return tokens as they're generated (SSE or WebSocket). The user sees the first token in ~200ms (after initial processing), then tokens stream in. Perceived latency is much lower than total generation time. (6) **Caching**: cache responses for common prompts. If the same prompt is asked, return the cached response instantly. (7) **Model distillation**: train a smaller model (distilled GPT-2, ~20M params) to mimic the 124M model. Inference 5-10x faster with acceptable quality loss. Recommendation: combine quantization (INT8, 2-4x speedup) + streaming (first token in ~200ms) + caching (instant for repeated prompts). This brings perceived latency under 500ms for most requests. For the remaining, use speculative decoding. If still not enough, distill to a smaller model. The key: total latency is less important than perceived latency. Streaming gives the user something to read immediately.

> [!question]- Q3. Compare TorchServe, Triton Inference Server, vLLM, and a custom FastAPI inference server. When would you choose each for serving a ML model?
**Answer:** TorchServe: PyTorch-specific model server. Built by PyTorch team. Supports model versioning, batching, metrics. Pros: PyTorch-native, simple setup, built-in batching. Cons: PyTorch-only, limited customization, not as performant as Triton. Best for: simple PyTorch model serving, quick deployment. Triton Inference Server: NVIDIA's multi-framework model server. Supports PyTorch, TensorFlow, ONNX, TensorRT. Pros: multi-framework, dynamic batching, model ensemble (chaining models), GPU sharing, metrics, best performance. Cons: NVIDIA-only (CUDA), complex configuration, steeper learning curve. Best for: production GPU serving, multiple models/frameworks, maximum performance. vLLM: LLM-specific serving engine. Uses PagedAttention for efficient memory management. Pros: 24x higher throughput for LLMs, continuous batching, streaming, speculative decoding. Cons: LLM-only (text generation), not for vision/classification. Best for: LLM serving (GPT, LLaMA, etc.), high-throughput text generation. Custom FastAPI: you build it yourself. Pros: full control, integrates with your existing FastAPI app, no new dependencies, flexible. Cons: you implement everything (batching, scaling, monitoring), less performant than optimized servers, more bugs. Best for: learning, simple models, when you need tight integration with FastAPI-specific logic, non-standard models. Recommendation: for production serving of vision models (DINOv2): Triton (best performance, multi-framework). For LLMs: vLLM (best throughput). For quick PyTorch deployment: TorchServe. For learning or simple cases: custom FastAPI. For a mixed workload (vision + LLM): Triton for vision, vLLM for LLM, FastAPI as the API gateway that routes to both.

> [!question]- Q4. Your ML inference API serves 10 different models. Each model is 2-5GB. The total GPU memory is 80GB (A100). Not all models fit simultaneously. Design the model loading and routing strategy.
**Answer:** With 10 models × avg 3.5GB = 35GB total, but only 80GB GPU memory, you can fit ~5-6 models at once. Strategy: (1) **Model tiering**: classify models by usage. Tier 1 (high traffic, 2 models): always loaded. Tier 2 (medium traffic, 3 models): loaded on demand, stay in memory if space. Tier 3 (low traffic, 5 models): loaded on demand, unloaded when not used. (2) **LRU cache**: keep the most recently used models in GPU memory. When a request comes for a model not in memory, load it. If GPU memory is full, evict the least recently used model. (3) **Model pre-fetching**: based on time-of-day patterns, pre-load models that will be needed. E.g., load analytics models at night, chat models during the day. (4) **CPU fallback**: for models not in GPU memory, run on CPU (slower but available). Or use a queue: if model is on CPU, queue the request and load to GPU when space is available. (5) **Model quantization**: quantize models to INT8 (4x smaller). 10 models × 1GB = 10GB — all fit in 80GB with room for batching. This is the most effective solution. (6) **Separate GPU instances**: if quantization doesn't work (accuracy loss), use multiple GPU instances. Each instance loads a subset of models. Route requests to the right instance based on the model needed. Recommendation: quantize all models to INT8 (test accuracy impact first). If acceptable, all models fit in GPU with LRU cache. If not, use tiered loading with LRU eviction + pre-fetching based on usage patterns. Route based on model tier and current GPU utilization. Monitor model access patterns and adjust tiering weekly.

> [!question]- Q5. A production ML model's accuracy drops from 95% to 82% over two weeks. The API latency and error rate are normal. Users don't complain immediately but gradually stop using the feature. Design a monitoring system that catches this before users notice.
**Answer:** The issue: accuracy degradation (model drift) without latency or error changes. Traditional monitoring (CPU, memory, latency, error rate) doesn't catch this. You need ML-specific monitoring: (1) **Input distribution monitoring**: track the statistical properties of incoming inputs (mean, std, feature distributions for tabular; image brightness/color histograms for vision; token distribution for text). Compare with the training/validation distribution using KL divergence or Population Stability Index (PSI). If PSI > 0.2, alert — input distribution has shifted significantly. (2) **Output distribution monitoring**: track the distribution of model predictions (class distribution for classification, value distribution for regression). Compare with baseline. If the model suddenly predicts 90% "class A" when it used to be 50%, something is wrong. (3) **Prediction confidence monitoring**: track the model's confidence scores (softmax max, prediction entropy). If average confidence drops, the model is less certain about its predictions — a sign of drift. (4) **Ground truth feedback loop**: when possible, collect ground truth (user corrections, delayed labels, manual audit). Compare predictions with ground truth to compute real-time accuracy. If accuracy drops below threshold, alert. This is the gold standard but requires ground truth availability. (5) **Shadow mode**: run the new model alongside the current production model. Compare predictions. If they diverge significantly, investigate. (6) **A/B testing with metrics**: track business metrics (user engagement, conversion, retention) for the model's predictions. If the model's output leads to worse business outcomes, even if accuracy is the same, the model has degraded in a meaningful way. Implementation: log every input and prediction to a monitoring database (ClickHouse, BigQuery). Run daily drift analysis jobs. Alert on PSI > 0.2, confidence drop > 20%, or accuracy drop > 5% (if ground truth available). For fast detection: sample 10% of requests for real-time analysis. The key: model drift doesn't affect API health metrics — you need ML-specific monitoring to catch it before users notice.

## Related
[[async-await-and-event-loop]]
[[concurrency-patterns]]
[[caching]]
[[rate-limiting]]
[[streaming-responses]]
[[background-workers-queues]]
[[performance-profiling]]
[[system-design-for-apis-at-scale]]
[[deployment-docker-uvicorn]]

#status/new