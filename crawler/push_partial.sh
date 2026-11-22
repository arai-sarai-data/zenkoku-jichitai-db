#!/usr/bin/env bash
# 県ごとの途中結果を results ブランチへすぐ保存する(全国の完了を待たずに確認できるように)。
# 使い方: bash crawler/push_partial.sh 19
set -u
PREF="$1"
git config user.name "collector-bot"
git config user.email "collector-bot@users.noreply.github.com"
for i in 1 2 3 4 5 6; do
  rm -rf /tmp/wt; git worktree prune
  if git fetch -q origin results 2>/dev/null; then
    git worktree add -q --detach /tmp/wt FETCH_HEAD
  else
    git worktree add -q --detach /tmp/wt HEAD
    (cd /tmp/wt && git checkout -q --orphan tmp-results && git rm -rqf . >/dev/null)
  fi
  mkdir -p /tmp/wt/links /tmp/wt/status /tmp/wt/docs
  cp "data/links/$PREF.csv"  /tmp/wt/links/  2>/dev/null || true
  cp "data/status/$PREF.csv" /tmp/wt/status/ 2>/dev/null || true
  cp "data/docs/$PREF.csv"   /tmp/wt/docs/   2>/dev/null || true
  ( cd /tmp/wt && git add links status docs && git commit -qm "results $PREF" && git push -q origin HEAD:refs/heads/results ) && break
  sleep $((RANDOM % 10 + 5))
done
rm -rf /tmp/wt; git worktree prune
