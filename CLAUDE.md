# Equibles

## Ops notes

- **FINRA API credential expires 2027-06-02.** On lapse, `FinraClient.GetAccessToken()` returns `400` and FINRA imports stop. Rotate at developer.finra.org, update `Finra__ClientId`/`Finra__ClientSecret` in `.env`, then `docker compose up -d worker` (recreate — `restart` won't reload env vars). See `docs/TODO.md`.
