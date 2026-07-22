#!/bin/bash
set -euo pipefail

usage() {
  echo "Usage: $0 <prod|staging|setup>"
  echo ""
  echo "  setup           Install all dependencies needed for deployment"
  echo "  prod|staging    Deploy to the specified environment"
  exit 1
}

setup() {
  echo "=== Setting up deployment dependencies ==="

  # Node.js
  if ! command -v node &>/dev/null; then
    echo "Installing Node.js..."
    brew install node
  else
    echo "Node.js already installed ($(node --version))"
  fi

  # Serverless Framework
  if ! command -v serverless &>/dev/null; then
    echo "Installing Serverless Framework..."
    npm install -g serverless
    echo "Logging into Serverless (required for v4)..."
    serverless login
  else
    echo "Serverless already installed ($(serverless --version 2>&1 | head -1))"
  fi

  # pipx (needed to install Poetry in an isolated environment)
  if ! command -v pipx &>/dev/null; then
    echo "Installing pipx..."
    brew install pipx
  else
    echo "pipx already installed"
  fi

  # Poetry via pipx (avoids Homebrew Python environment conflicts)
  if pipx list 2>/dev/null | grep -q "package poetry"; then
    echo "Poetry already installed via pipx ($(poetry --version))"
  else
    if command -v poetry &>/dev/null; then
      echo "WARNING: Poetry is installed but not via pipx ($(poetry --version))."
      echo "To avoid conflicts, uninstall it first (e.g. 'brew uninstall poetry') then re-run setup."
      exit 1
    fi
    echo "Installing Poetry via pipx..."
    pipx install poetry
  fi

  # poetry-plugin-export (required for `poetry export` in Poetry 1.2+)
  if pipx list 2>/dev/null | grep -A5 "package poetry" | grep -q "poetry-plugin-export"; then
    echo "poetry-plugin-export already installed"
  else
    echo "Installing poetry-plugin-export..."
    pipx inject poetry poetry-plugin-export
  fi

  # Docker
  if ! command -v docker &>/dev/null; then
    echo "Docker not found. Install Docker Desktop from https://www.docker.com/products/docker-desktop/"
    echo "Or run: brew install --cask docker"
    echo "Then launch Docker Desktop before deploying."
  else
    echo "Docker already installed ($(docker --version))"
  fi

  # AWS credentials
  if [[ ! -f "$HOME/.aws/credentials" && -z "${AWS_ACCESS_KEY_ID:-}" ]]; then
    echo "WARNING: No AWS credentials found. Set up ~/.aws/credentials or export AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY before deploying."
  else
    echo "AWS credentials found"
  fi

  echo ""
  echo "=== Setup complete. Run '$0 staging' or '$0 prod' to deploy. ==="
}

deploy() {
  local stage="$1"
  local config_file="serverless-${stage}.yml"

  if ! command -v docker &>/dev/null || ! docker info &>/dev/null 2>&1; then
    echo "ERROR: Docker is not running. Start Docker Desktop before deploying."
    exit 1
  fi

  echo "Deploying newrelic-log-ingestion to ${stage}..."
  npx serverless deploy --config "$config_file"
  echo "Done."
}

CMD="${1:-}"

case "$CMD" in
  setup)             setup ;;
  prod|staging)      deploy "$CMD" ;;
  *)                 usage ;;
esac
