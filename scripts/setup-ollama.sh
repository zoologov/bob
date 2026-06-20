#!/usr/bin/env bash
# Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
# SPDX-License-Identifier: BUSL-1.1
#
# Bobiverse local setup — installs Ollama + the local models Bob's MEMORY needs:
#   * embedder : BGE-M3      (dense 1024, multilingual incl. Russian)  [REQUIRED]
#   * reranker : Qwen3-Reranker                                        [best-effort; see BOB-011 Q1]
#
# Target: macOS on Apple Silicon (Mac Mini M4, etc.). Idempotent — safe to re-run.
# Everything stays LOCAL: no memory content ever leaves the machine.
#
# Usage:   bash scripts/setup-ollama.sh
# Override models: EMBED_MODEL=bge-m3 RERANK_MODEL=<tag> bash scripts/setup-ollama.sh
set -euo pipefail

EMBED_MODEL="${EMBED_MODEL:-bge-m3}"
# Reranker tag: the exact local reranker + serving is finalized in BOB-011 BEAD-04 (Q1).
# Best-effort here; the embedder alone is enough to start the memory work.
RERANK_MODEL="${RERANK_MODEL:-dengcao/Qwen3-Reranker-0.6B}"
OLLAMA_HOST_URL="http://localhost:11434"

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[warn] %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m[err]  %s\033[0m\n' "$*"; exit 1; }

# 1. OS sanity
if [ "$(uname -s)" != "Darwin" ]; then
  warn "Designed for macOS/Apple Silicon. Detected $(uname -s); on Linux use https://ollama.com/install.sh, then re-run from step 5."
fi

# 2. Homebrew (the macOS install path)
if ! command -v brew >/dev/null 2>&1; then
  die "Homebrew not found. Install it from https://brew.sh and re-run."
fi

# 3. Install Ollama if missing
if ! command -v ollama >/dev/null 2>&1; then
  log "Installing Ollama via Homebrew..."
  brew install ollama
else
  log "Ollama already present: $(ollama --version 2>&1 | head -1)"
fi

# 4. Ensure the Ollama server is up
if ! curl -sS -m 3 "${OLLAMA_HOST_URL}/api/version" >/dev/null 2>&1; then
  log "Starting the Ollama service..."
  brew services start ollama >/dev/null 2>&1 || nohup ollama serve >/tmp/ollama-serve.log 2>&1 &
  for _ in $(seq 1 40); do
    if curl -sS -m 2 "${OLLAMA_HOST_URL}/api/version" >/dev/null 2>&1; then break; fi
    sleep 1
  done
fi
curl -sS -m 4 "${OLLAMA_HOST_URL}/api/version" >/dev/null 2>&1 \
  && log "Ollama server is up at ${OLLAMA_HOST_URL}" \
  || die "Ollama server did not come up — check /tmp/ollama-serve.log"

# 5. Pull the embedder (REQUIRED for Bob's semantic memory)
log "Pulling embedder model: ${EMBED_MODEL}"
ollama pull "${EMBED_MODEL}"

# 6. Pull the reranker (best-effort; final tag/serving decided in BOB-011 BEAD-04)
log "Pulling reranker model: ${RERANK_MODEL}"
if ! ollama pull "${RERANK_MODEL}"; then
  warn "Reranker pull failed for '${RERANK_MODEL}'."
  warn "That's OK to start: the exact local reranker + how to serve it is finalized in BOB-011 BEAD-04 (Q1)."
  warn "Override later with: RERANK_MODEL=<tag> bash scripts/setup-ollama.sh"
fi

# 7. Verify
log "Installed Ollama models:"
ollama list

log "Done. Bob's local memory stack is ready (embedder=${EMBED_MODEL}). Everything runs locally + private."
