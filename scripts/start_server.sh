llama-server \
  --model /models/Ternary-Bonsai-27B-Q2_0.gguf \
  --host 0.0.0.0 \
  --port 8080 \
  --ctx-size 131072 \
  --parallel 2 \
  --cache-type-k q8_0 \
  --cache-type-v q8_0