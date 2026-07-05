# Changelog

## [1.0.0](https://github.com/alex-matthews/costanza/compare/v0.1.0...v1.0.0) (2026-07-05)


### ⚠ BREAKING CHANGES

* **ops:** the image no longer creates a user or /data, ships no /config/routing.yaml, and defaults to nobody:nogroup — deployments must supply runAsUser/fsGroup and mount config explicitly.

### Features

* **adapters:** supervised discord.py notifier behind the port ([b5fd331](https://github.com/alex-matthews/costanza/commit/b5fd33117d12a442796911602adfded9f1590913))
* **api:** read API, kill-switch endpoint, metrics, runtime wiring, replay ([3aff15c](https://github.com/alex-matthews/costanza/commit/3aff15ca3918821d9dd1b30ad038a3d4930fd747))
* **correlate:** media identity, identity map, request chains ([ce87bca](https://github.com/alex-matthews/costanza/commit/ce87bca36191d70bcb67d07755f6de7c864faf49))
* **docker:** read-only-rootfs hardening and deploy guidance ([82c2c20](https://github.com/alex-matthews/costanza/commit/82c2c20a42602da02a2323fdb4fa21ed7dfad6fa))
* **docker:** uv multi-stage nonroot image, deploy notes, quickstart ([7e4ecb9](https://github.com/alex-matthews/costanza/commit/7e4ecb9c1cc3635dfebefffc5c68443f5576e086))
* **ingest:** webhook ingestion, raw archive, SQLite outbox worker ([429594b](https://github.com/alex-matthews/costanza/commit/429594ba4bb7fa3528ac45e092219a964c8ed739))
* **jobs:** reconcile per guarantees matrix, digest, prune, identity_sync ([64ab3ca](https://github.com/alex-matthews/costanza/commit/64ab3ca3444299bd10db9a242c875b393442b9b0))
* **normalize:** per-source normalizers with golden fixture suite ([e94ea55](https://github.com/alex-matthews/costanza/commit/e94ea55a1224671b12e2b8341018f15c7310700f))
* **notify:** router, pure renderers, limits, ledger-outbox pipeline ([faaf7cd](https://github.com/alex-matthews/costanza/commit/faaf7cdb3e3e996ba71f7b1c1e127bd57af1598c))
* **store:** SQLite WAL store, versioned migrations, env-first config ([0490241](https://github.com/alex-matthews/costanza/commit/0490241fbc540661e3267ba26054a8a63661d686))


### Bug Fixes

* hardening pass — secret hygiene, digest stability, crash-safe processing, raw retention ([dcd131b](https://github.com/alex-matthews/costanza/commit/dcd131bf664c0af083b5e3f297af718a9073b83a))
* **ops:** identity-agnostic alpine image, cluster securityContext docs, k8s smoke ([503c97a](https://github.com/alex-matthews/costanza/commit/503c97ae160256a2414560577ac93bf4ad5d62a3))
* **ops:** stable /config and /data mount targets; stale doc cleanup ([b9ef324](https://github.com/alex-matthews/costanza/commit/b9ef324144e329d524f873fc4d31fe5468e701d9))
* **reconcile:** repair notifications lost to crashes after event insert ([b1cb284](https://github.com/alex-matthews/costanza/commit/b1cb284960c66f9d4e8f4a915f686dde792307cb))


### Documentation

* align architecture runtime line with Resolute-pinned Python ([c22e465](https://github.com/alex-matthews/costanza/commit/c22e465f8da1d2208f2dd376ada378d4e7714024))
* answer OQ-1 (radarr-se out of v1 scope) and pin 202-always webhook semantics ([0fb9369](https://github.com/alex-matthews/costanza/commit/0fb9369c88b3c602870280937fb78c93f2411ed3))
* Costanza v1 design pack ([be2d465](https://github.com/alex-matthews/costanza/commit/be2d465c4bff162961ba97dd40f2a9f7a3cab6de))
* council v1 design pack, doc reframe, and review-round hardening ([#2](https://github.com/alex-matthews/costanza/issues/2)) ([e1fd1a7](https://github.com/alex-matthews/costanza/commit/e1fd1a7721c3aba4f2335c691750559dadc5abde))
* index build prompt in README ([182e673](https://github.com/alex-matthews/costanza/commit/182e67342be23736ec44499f9a312b388ccbe371))
* record v1 build notes (deviations, choices, discoveries) ([012627f](https://github.com/alex-matthews/costanza/commit/012627f54f7ec6d8239fa515f011da08c3aceb35))
* remove remaining Resolute-as-house-style residuals ([40fb29c](https://github.com/alex-matthews/costanza/commit/40fb29c6efb3bba7fd0489ddb0bcbef72a0e000a))
* scoped v1 build prompt ([ae8e676](https://github.com/alex-matthews/costanza/commit/ae8e676e15cea292ba13427fde097baf7cef4d2a))
