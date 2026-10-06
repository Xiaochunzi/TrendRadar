#!/usr/bin/env bash
# Run locally after installing GitHub CLI and completing `gh auth login`.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v gh >/dev/null || { echo '请先安装 GitHub CLI，并运行 gh auth login'; exit 1; }
gh auth status >/dev/null
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  SOURCE_DIR="$PWD"
  CHECKOUT_DIR=$(mktemp -d)
  git clone --depth 1 https://github.com/sansan0/TrendRadar.git "$CHECKOUT_DIR/TrendRadar"
  tar --exclude=.git --exclude=.venv --exclude=output --exclude=__pycache__ -cf - . | tar -xf - -C "$CHECKOUT_DIR/TrendRadar"
  cd "$CHECKOUT_DIR/TrendRadar"
  git switch -c feat/ai-frontier-radar
  git add .
  git -c user.name=Codex -c user.email=codex@users.noreply.github.com commit -m 'Add evidence-first AI frontier radar with Bark delivery'
fi
LOGIN=$(gh api user --jq .login)
gh repo fork sansan0/TrendRadar --clone=false --remote=false
if git remote get-url origin >/dev/null 2>&1; then
  if [ "$(git remote get-url origin)" = 'https://github.com/sansan0/TrendRadar.git' ]; then
    git remote rename origin upstream
  fi
fi
if ! git remote get-url origin >/dev/null 2>&1; then
  git remote add origin "https://github.com/$LOGIN/TrendRadar.git"
fi
TARGET=$(git remote get-url origin)
if [ "$TARGET" != "https://github.com/$LOGIN/TrendRadar.git" ]; then
  echo 'origin 不指向当前账号的 TrendRadar；请核实后再运行。'
  exit 1
fi
gh auth setup-git
git push -u origin feat/ai-frontier-radar
echo "已保存开发分支：https://github.com/$LOGIN/TrendRadar/tree/feat/ai-frontier-radar"
