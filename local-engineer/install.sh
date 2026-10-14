#!/bin/zsh
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/.local/share/local-engineer"
CFG="$HOME/.config/local-engineer"
mkdir -p "$APP" "$CFG" "$HOME/bin" "$HOME/.local/state/local-engineer"
# Keep the command pointed at the source checkout instead of copying Python files.
# This makes \`git pull\` immediately effective and prevents stale runtime modules.
cp "$SRC/llm" "$HOME/bin/llm"
chmod +x "$SRC/local_engineer.py" "$HOME/bin/llm"
cat > "$HOME/bin/local-engineer" <<WRAP
#!/bin/zsh
exec /usr/bin/env python3 "$SRC/local_engineer.py" "\$@"
WRAP
cat > "$HOME/bin/local-engineer-qwen" <<WRAP
#!/bin/zsh
set -e
API_BASE="${LOCAL_ENGINEER_API_BASE:-http://127.0.0.1:11434/v1}"
if ! /usr/bin/curl -fsS --max-time 3 "${API_BASE}/models" >/dev/null; then
  echo "[ERR] Ollama API is not responding at ${API_BASE}" >&2
  echo "Start Ollama with: /Applications/Ollama.app/Contents/Resources/ollama serve" >&2
  exit 1
fi
export LOCAL_ENGINEER_API_BASE="${API_BASE}"
export LOCAL_ENGINEER_ALLOW_NON_BONSAI=1
exec /usr/bin/env python3 "$SRC/local_engineer.py" "\$@"
WRAP
chmod +x "$HOME/bin/local-engineer" "$HOME/bin/local-engineer-qwen"
if [ ! -f "$CFG/projects.json" ]; then
  cp "$SRC/projects.json" "$CFG/projects.json"
  echo "[OK] installed default config: $CFG/projects.json"
else
  echo "[KEEP] existing config: $CFG/projects.json"
fi
if ! grep -q 'export PATH="$HOME/bin:$PATH"' "$HOME/.zshrc" 2>/dev/null; then
  echo 'export PATH="$HOME/bin:$PATH"' >> "$HOME/.zshrc"
fi
export PATH="$HOME/bin:$PATH"
echo "[OK] installed: $HOME/bin/llm"
echo "[OK] installed: $HOME/bin/local-engineer"
echo
echo "Try:"
echo "  llm status"
echo "  local-engineer projects"
echo "  local-engineer discover"
