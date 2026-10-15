# Third-party notices

Original gateway/client/synchronization code is covered by LICENSE.

- `deployment/patches/rclone-v1.75.2-china.patch` contains changes derived from [xz-dev's rclone PR #9399](https://github.com/rclone/rclone/pull/9399), reviewed at head `f56bd5bcc98b37cf91edce99ad95e8ec07e4faab`, plus local region-specific OAuth redirect adjustments. Base: rclone v1.75.2. Preserve [rclone's MIT license](licenses/rclone-MIT.txt) and upstream attribution. This is an experimental build, not a merged upstream release.
- The Web Push helper imports `github.com/SherClockHolmes/webpush-go` v1.4.0 (MIT), `github.com/golang-jwt/jwt/v5` v5.2.1 (MIT), and `golang.org/x/crypto` v0.31.0 (BSD-style). Exact versions and module checksums are in `gateway-ui/webpush-helper/go.mod` and `go.sum`; dependencies are downloaded, not vendored. Preserve their upstream license notices if redistributing a built binary.
- Tailscale and Go are separate downloaded tools, not relicensed by this repository. Preserve their distribution licenses when redistributing them.
- User-managed Skills, third-party plugin caches, personal settings and their licenses are intentionally absent. Review each Skill's redistribution rights before publishing your own content.
- The optional live autosave acceptance script uses independently installed XeLaTeX and PyMuPDF to create and inspect a synthetic PDF. Their source and binaries are not bundled or relicensed here; follow their own distribution terms when installing or packaging those runtimes.
