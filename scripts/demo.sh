#!/usr/bin/env bash
# Run the three CABER intelligence demonstrations against a running backend.
#
# Usage: scripts/demo.sh [backend_url]
set -euo pipefail

BASE="${1:-http://127.0.0.1:12000}"

echo "==> Health"
curl -sS "$BASE/api/health" | python3 -m json.tool

echo
echo "==> CABER Intelligence C — building creation"
curl -sS -X POST "$BASE/api/caber/buildings" \
  -H 'Content-Type: application/json' \
  -d '{"request":"Design a modern two-storey villa with three bedrooms, open-plan living and kitchen, a study, two bathrooms, a terrace and a pool.","preferences":"minimalist, natural light, warm wood"}' \
  | python3 -c "
import json,sys
d=json.load(sys.stdin)
v=d.get('validation') or {}
print('project:', d['project_id'])
print('validation score:', v.get('score'), 'passed:', v.get('passed'))
for c in v.get('checks', []):
    print(('  PASS ' if c['passed'] else '  FAIL '), c['name'], '-', c['detail'])
print('viewer:', BASE + d['viewer_url'])
" BASE="$BASE"

echo
echo "==> CABER Intelligence B — problem solving"
curl -sS -X POST "$BASE/api/solve" \
  -H 'Content-Type: application/json' \
  -d '{"problem":"For a web service under Poisson arrivals at 40 requests/second with 12 ms mean service time, compare a single queue against 4 parallel queues, and report the expected waiting time for each."}' \
  | python3 -c "
import json,sys
d=json.load(sys.stdin)
r=d['report']
print('project:', d['project_id'])
print('confidence:', r['confidence'])
print('computation succeeded:', r['computation']['succeeded'])
print('approach:', (r.get('approach') or '')[:300])
for f in r.get('findings', [])[:5]:
    print('  -', f[:220])
for l in r.get('limitations', [])[:4]:
    print('  limitation:', l[:200])
"

echo
echo "==> CABER Intelligence A — application creation (starts a run)"
curl -sS -X POST "$BASE/api/projects" \
  -H 'Content-Type: application/json' \
  -d '{"request":"Build an enterprise-grade task-management application with an original premium UI/UX, responsive frontend, backend, authentication, database, task management, user roles, analytics, API documentation and automated tests.","name":"Enterprise Task Manager","auto_start":true}' \
  | python3 -c "
import json,sys
p=json.load(sys.stdin)['project']
print('project:', p['id'], '-', p['name'])
print('watch:  ' + BASE + '/api/projects/' + p['id'])
print('stream: ' + BASE + '/api/projects/' + p['id'] + '/stream')
"
