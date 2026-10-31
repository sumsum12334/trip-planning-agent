# Qwen model service job

Submit this directory first:

```bash
cd tacc/qwen-public-serve
tcloud submit
tcloud ps -j MODEL_JOB_ID
tcloud cat slurm_log/qwen-public-serve-MODEL_JOB_ID.log
```

Wait for `SERVICE_BASE_URL=http://NODE:8000/v1` and for the service startup
message. Copy that URL into the repository-root `server-url.txt`.

The service uses the course-provided `QWEN_PROJECT_ROOT/serve.sh`; no model
weights, CUDA packages, or `tacc_reference` files are required in this
repository.
