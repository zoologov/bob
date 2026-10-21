---
title: identity
kind: feature
---

# identity

**Kind:** feature

Identity module («кем Боб представляется GitHub'у») — github-идентичность как отдельный bounded context: чистые ядра (Purpose→Principal — work пушит только в форк, propose лишь читает апстрим; реквизиты принципала из конфига с проверкой формы; claims App-JWT RS256 с поправкой на расхождение часов и предел GitHub; вердикт «токен годен / пора обновить» с обновлением ЗАРАНЕЕ, а не по факту 401) и `adapters/` (подпись настоящим `openssl dgst -sha256 -sign` — без новых зависимостей; транспорт двух ручек GitHub App API на aiohttp — секрет только в заголовке, никогда в argv; кэш installation-токенов на принципала). Заведён в BOB-089 срез B; `coding` его не импортит, провайдер приходит на композиции.

**Source:** `src/bob/identity/`

## Public symbols

- `AiohttpGitHubAppApi`
- `AppCredentials`
- `Freshness`
- `GitHubAppApi`
- `GitHubInstallationTokens`
- `IdentityConfigError`
- `IdentityError`
- `InstallationToken`
- `InstallationTokenSource`
- `OpensslRs256Signer`
- `Principal`
- `Purpose`
- `Rs256Signer`
- `SigningError`
- `SpawnIsolation`
- `SpawnIsolationFiles`
- `TokenMintError`
- `assemble_jwt`
- `b64url`
- `build_installation_tokens`
- `controlled_ssh_command`
- `credential_store_line`
- `credentials_for`
- `isolation_config_pairs`
- `isolation_env`
- `jwt_claims`
- `parse_expiry`
- `principal_for`
- `sign_argv`
- `signing_input`
- `token_freshness`

## Relationships

- **part_of**: [bob-domain](../domains/bob-domain.md)
- **depends_on**: [bob-domain](../domains/bob-domain.md)
- **Used by**: [coding](../features/coding.md), [interactive](../features/interactive.md), [runtime](../services/runtime.md)

## Documentation

- [domains/identity/README.md](/docs/domains/identity/README.md)

## Graph

<ClientOnly>
  <ArchitectureMap focus="identity" :depth="1" height="60vh" />
</ClientOnly>

