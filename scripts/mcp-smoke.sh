#!/usr/bin/env bash
# Smoke test des lectures MCP Atlassian.
#
# Il n'existe pas d'endpoint de ping : la seule facon de verifier la connexion
# est d'executer une vraie lecture, qui traverse toute la chaine (allowlist,
# validation de schema, detection de derive, injection du cloudId, appel
# distant, audit).
#
#   ./scripts/mcp-smoke.sh
#   API_BASE_URL=http://127.0.0.1:8000 ./scripts/mcp-smoke.sh
set -uo pipefail

API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8000}"
# Doivent correspondre a PKA_MCP_ATLASSIAN_GRANT_TENANT_ID / _USER_ID : le grant
# est indexe par (provider, tenant, user), un ecart donne un 503.
TENANT_ID="${MCP_TENANT_ID:-development-tenant}"
USER_ID="${MCP_USER_ID:-development-user}"

failures=0

probe() {
  local label="$1" source_system="$2" tool_name="$3" arguments="$4"
  local payload response body http_code

  printf '%-46s ' "${label}"
  payload=$(printf \
    '{"calls":[{"source_system":"%s","tool_name":"%s","arguments":%s}]}' \
    "${source_system}" "${tool_name}" "${arguments}")

  response=$(curl -sS -m 45 -w $'\n%{http_code}' \
    -X POST "${API_BASE_URL}/api/mcp/reads" \
    -H 'Content-Type: application/json' \
    -H "X-Tenant-ID: ${TENANT_ID}" \
    -H "X-User-ID: ${USER_ID}" \
    -d "${payload}" 2>&1) || {
      printf 'INJOIGNABLE  %s\n' "${response}"
      failures=$((failures + 1))
      return
    }

  http_code="${response##*$'\n'}"
  body="${response%$'\n'*}"

  if [ "${http_code}" = "200" ]; then
    printf 'OK\n'
    return
  fi

  # Le code MCP est dans detail.code ; c'est lui qui dit quoi corriger, pas le
  # statut HTTP, qui regroupe plusieurs causes distinctes sous 502.
  local mcp_code
  mcp_code=$(printf '%s' "${body}" \
    | sed -n 's/.*"code"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
  printf 'HTTP %s  %s\n' "${http_code}" "${mcp_code:-${body}}"
  failures=$((failures + 1))
}

printf 'Cible : %s   identite : %s / %s\n\n' \
  "${API_BASE_URL}" "${TENANT_ID}" "${USER_ID}"

# Sans argument ni cloudId : un echec ici ne peut venir que du jeton ou du reseau.
probe 'atlassian  atlassianUserInfo' \
  atlassian atlassianUserInfo '{}'
probe 'atlassian  getAccessibleAtlassianResources' \
  atlassian getAccessibleAtlassianResources '{}'
# Les deux suivants valident en plus l'injection du cloudId cote serveur.
probe 'jira       getVisibleJiraProjects' \
  jira getVisibleJiraProjects '{}'
probe 'confluence getConfluenceSpaces' \
  confluence getConfluenceSpaces '{"limit":1}'

printf '\n'
if [ "${failures}" -eq 0 ]; then
  printf 'Connexion MCP operationnelle.\n'
  exit 0
fi

printf '%d sonde(s) en echec.\n' "${failures}"
cat <<'EOF'

  MCP_TRANSPORT_FAILURE   jeton expire (~1 h) -- le cas le plus frequent
  MCP_GRANT_UNAVAILABLE   identite ou fichier secret absent
  MCP_PROVIDER_DISABLED   une surcouche compose manque
  MCP_PROTOCOL_REJECTED   Atlassian a change de version negociee
  MCP_SCHEMA_REJECTED     derive de schema cote Atlassian
  MCP_REMOTE_TOOL_FAILURE cloudId errone, ou arguments refuses

Renouvellement du jeton :
  npx -y mcp-remote https://mcp.atlassian.com/v1/mcp
  puis recopier access_token dans infra/secrets/dev/atlassian_bearer_token
  avec un editeur de texte, et recreer le conteneur :
  docker compose -f compose.yaml -f compose.atlassian.yaml \
                 -f compose.atlassian-bindings.yaml up -d --force-recreate api
EOF
exit 1
