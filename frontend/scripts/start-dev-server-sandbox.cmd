@echo off
subst X: "C:\Users\alger\Documents\000. Projects\005. evergreen funds platform xbrl" >nul 2>nul
cd /d X:\frontend
set NODE_OPTIONS=-r X:\frontend\scripts\dev-sandbox-realpath-fallback.cjs
node .\node_modules\next\dist\bin\next dev --hostname 127.0.0.1 --port 3000
