# Secret exposure — verified 2026-08-16

Scope: `browngkenneth1988-crypto/youtube-shorts-pipeline` (public fork of
`rushindrasinha/youtube-shorts-pipeline`, a 515-fork network).

## Three secrets, one file, two commits

All in `scripts/daily_run.bat`, on branch `claude/automate-youtube-shorts-ujgkW`
only. **Not in `main`.**

The exposed commits are **`cb2723a`** (added the keys) and **`c949a90`** (carries
the same blob forward). Both still return the file with all three keys in
plaintext. `42e0ee1` is the commit that **removed** them and contains none — an
earlier version of this document named it as an exposed commit, which was wrong.
`git log --find-object` matches a blob's removal as well as its addition, and
that is what misled. Verified against the live API:

| Commit | Credentials returned |
|---|---|
| `cb2723a` | 3 |
| `c949a90` | 3 |
| `42e0ee1` | 0 |

| Secret | First tested 2026-08-16 | Now |
|---|---|---|
| `ELEVENLABS_API_KEY` `sk_407e…f3c6` | **LIVE** — HTTP 200 on `/v1/voices`, `/v1/models` | **Revoked** — `401 invalid_api_key`, confirmed by probe |
| `GEMINI_API_KEY` `AIzaSy…gu7A` | Dead — `400 API_KEY_INVALID` (Google auto-flagged it) | Dead |
| `LEONARDO_API_KEY` `a70c59de…` | Dead — `401` on all endpoints | Dead |

**All three are now dead. No live credential remains exposed.**

The original report flagged Gemini as the risk. Gemini was already dead. The
live credential was **ElevenLabs**, which that report did not mention — and it
initially looked dead too, returning `401`. The tell was the error code:
`missing_permissions` for the `user_read` scope is an *authorization* failure on
a valid key, not an authentication failure. After revocation the same endpoints
return `invalid_api_key`. When triaging a suspected-live key, read the error
body, not just the status code.

Revoking broke nothing: `scripts/secrets.bat` defines only `GEMINI_API_KEY` and
`LEONARDO_API_KEY`, so nothing local consumed the ElevenLabs key.

## Do NOT force-push to purge — it will not work

The file is anonymously retrievable **through the parent repo**:

```
GET /repos/rushindrasinha/youtube-shorts-pipeline/contents/scripts/daily_run.bat?ref=cb2723a
→ 200, full plaintext secrets
```

GitHub stores all repos in a fork network in shared object storage. A commit
pushed to any fork stays reachable by SHA from the parent and all 515 siblings
even after the fork force-pushes or is deleted. Rewriting this fork's history
would cost a force-push over 29 commits of real work and would not remove the
blob from the network.

Only GitHub Support can purge network-cached objects. That request is worth
filing *after* revocation, as cleanup — not as the fix. Draft below.

Because the blob is permanently public, treat any secret committed to this repo
as burned the moment it is pushed. Revoke; do not attempt to unpublish.

## Rest of history is clean

Scanned all 549 blobs in the object database (including unreachable objects)
against 14 credential patterns — Google, ElevenLabs, OpenAI, Anthropic, GitHub,
AWS, Slack, Stripe, private-key blocks, Google OAuth client/secret/refresh
tokens, and generic assignments. Only the three above are real. The remaining
matches are variable assignments (`api_key = get_gemini_key()`), not literals.

`scripts/secrets.bat` is gitignored and untracked — correctly protected.

## Paste-ready GitHub Support request (after revoking)

> Subject: Purge cached commits containing leaked credentials from fork network
>
> Repository: browngkenneth1988-crypto/youtube-shorts-pipeline
> Fork network root: rushindrasinha/youtube-shorts-pipeline
>
> Two commits expose plaintext API keys in `scripts/daily_run.bat`, at lines
> 8-10 (`GEMINI_API_KEY`, `LEONARDO_API_KEY`, `ELEVENLABS_API_KEY`):
> - cb2723ae9e7587e5a4b9c94230cb595a365426f5
> - c949a90ed19772fdb178f59ab62dc4b099cab56f
>
> All three credentials have already been revoked and verified dead, so this is
> a cleanup request, not an active incident. The branch carrying these commits
> has been deleted from my fork, but the objects stay anonymously retrievable by
> SHA through the parent repository's fork network, so self-service history
> rewriting cannot reach them. Please purge these objects from the network cache.

Note before sending: GitHub's private-information form at
`support.github.com/contact/private-information` is scoped to credentials
*someone else* posted without authorization, and it redirects owners of the
repository to self-service instructions. It also asks how each item poses a
security risk — and for revoked keys, none does. Expect this to be declined,
and do not overstate the risk to get it accepted.
