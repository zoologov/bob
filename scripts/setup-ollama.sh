#!/usr/bin/env bash
# Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
# SPDX-License-Identifier: BUSL-1.1
#
# Bobiverse local setup — installs Ollama (STANDALONE, no Homebrew) + the local
# models Bob's MEMORY needs:
#   * embedder : BGE-M3   (dense 1024, multilingual incl. Russian)  [REQUIRED]
#   * reranker : Qwen3-Reranker                                     [best-effort; see BOB-011 Q1]
#
# Why standalone (NOT `brew install ollama`): the Homebrew formula pulls python@3.14
# as a dependency and can upgrade it, which BREAKS any uv/venv that points at the old
# Python. The standalone tarball is a self-contained CLI + libs — it touches nothing
# else on the machine. Everything stays LOCAL: no memory content ever leaves the box.
#
# Target: macOS on Apple Silicon (Mac Mini M4, etc.). Idempotent — safe to re-run.
#
# Usage:   bash scripts/setup-ollama.sh
# Override: EMBED_MODEL=bge-m3 RERANK_MODEL=<tag> OLLAMA_DIR=~/.local/ollama bash scripts/setup-ollama.sh
set -euo pipefail

EMBED_MODEL="${EMBED_MODEL:-bge-m3}"
# Reranker tag: exact model + local serving finalized in BOB-011 BEAD-04 (Q1). Best-effort here.
RERANK_MODEL="${RERANK_MODEL:-bge-reranker-v2-m3}"
OLLAMA_DIR="${OLLAMA_DIR:-$HOME/.local/ollama}"
OLLAMA_TGZ="https://github.com/ollama/ollama/releases/latest/download/ollama-darwin.tgz"
OLLAMA_HOST_URL="http://localhost:11434"

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[warn] %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m[err]  %s\033[0m\n' "$*"; exit 1; }

# 1. OS sanity
if [ "$(uname -s)" != "Darwin" ]; then
  warn "Designed for macOS/Apple Silicon. On Linux use https://ollama.com/install.sh, then re-run from step 4."
fi

# 2. Install Ollama STANDALONE if missing (no Homebrew, no Python touched)
if ! command -v ollama >/dev/null 2>&1 && [ ! -x "${OLLAMA_DIR}/ollama" ]; then
  log "Installing standalone Ollama into ${OLLAMA_DIR} (no Homebrew)..."
  mkdir -p "${OLLAMA_DIR}"
  curl -fsSL "${OLLAMA_TGZ}" -o /tmp/ollama-darwin.tgz || die "Download failed: ${OLLAMA_TGZ}"
  tar -xzf /tmp/ollama-darwin.tgz -C "${OLLAMA_DIR}"   # ollama binary + libggml*/dylibs (kept side-by-side)
  rm -f /tmp/ollama-darwin.tgz
  # Persist on PATH for future shells (binary finds its libs from its own dir).
  PROFILE="${HOME}/.zprofile"
  if ! grep -qs "${OLLAMA_DIR}" "${PROFILE}" 2>/dev/null; then
    printf '\n# Ollama (Bobiverse standalone install)\nexport PATH="%s:$PATH"\n' "${OLLAMA_DIR}" >> "${PROFILE}"
  fi
fi
# Make ollama callable in THIS session.
if ! command -v ollama >/dev/null 2>&1; then export PATH="${OLLAMA_DIR}:$PATH"; fi
command -v ollama >/dev/null 2>&1 || die "ollama not on PATH after install."
log "Ollama: $(ollama --version 2>&1 | head -1)"

# 3. Start the Ollama server (headless)
if ! curl -sS -m 3 "${OLLAMA_HOST_URL}/api/version" >/dev/null 2>&1; then
  log "Starting the Ollama server (headless)..."
  nohup ollama serve >/tmp/ollama-serve.log 2>&1 &
  for _ in $(seq 1 40); do
    if curl -sS -m 2 "${OLLAMA_HOST_URL}/api/version" >/dev/null 2>&1; then break; fi
    sleep 1
  done
fi
curl -sS -m 4 "${OLLAMA_HOST_URL}/api/version" >/dev/null 2>&1 \
  && log "Ollama server is up at ${OLLAMA_HOST_URL}" \
  || die "Ollama server did not come up — check /tmp/ollama-serve.log"

# 4. Pull the embedder (REQUIRED for Bob's semantic memory)
log "Pulling embedder model: ${EMBED_MODEL}"
ollama pull "${EMBED_MODEL}"

# 5. Pull the reranker (best-effort; final tag/serving decided in BOB-011 BEAD-04)
log "Pulling reranker model: ${RERANK_MODEL}"
if ! ollama pull "${RERANK_MODEL}"; then
  warn "Reranker pull failed for '${RERANK_MODEL}' — OK to start; finalized in BOB-011 BEAD-04 (Q1)."
  warn "Override later: RERANK_MODEL=<tag> bash scripts/setup-ollama.sh"
fi

# 6. Verify
log "Installed Ollama models:"
ollama list
log "Done. Bob's local memory stack is ready (embedder=${EMBED_MODEL}). Local + private; nothing touched but ${OLLAMA_DIR}."
