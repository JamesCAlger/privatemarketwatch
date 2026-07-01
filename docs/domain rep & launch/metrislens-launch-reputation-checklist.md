# Domain Reputation & Launch Checklist: metrislens.com

**Date:** 23 June 2026
**Context:** New domain replacing privatemarketwatch.com. Goal — launch with the trust/reputation signals in place from day one so the site is **not** caught by Forcepoint (or other corporate firewalls) under the "Newly Registered Websites" category.

---

## Current State (checked 23 June 2026)

| Item | Status | Detail |
|------|--------|--------|
| Domain registration | ✅ Registered | Namecheap (`dns1/dns2.registrar-servers.com` nameservers). Exact creation date not retrievable this session (WHOIS query timed out). |
| Site live? | ❌ Parked | `www.metrislens.com` → `parkingpage.namecheap.com`; apex `A` → `192.64.119.77` (Namecheap parking). The real site is **not** pointed here yet. |
| SSL / HTTPS | ⏳ N/A yet | Will be provisioned once the domain points at the real host (e.g. Vercel auto-issues Let's Encrypt). |
| MX (mail) | ✅ Present | Namecheap email forwarding (`eforward1–5.registrar-servers.com`). |
| SPF | ✅ Present | `v=spf1 include:spf.efwd.registrar-servers.com ~all` — valid for the forwarding service. |
| DMARC | ❌ Missing | No record at `_dmarc.metrislens.com`. |
| DKIM | ⚠️ None found | No record on the 9 common selectors checked (expected for forwarding-only; only needed if you send signed mail). |
| CAA | ➖ None | No CAA record. Not a problem (absence = any CA may issue); optional to add. |
| Search indexing | ❌ Not indexed | `site:metrislens.com` returns zero results. No search presence yet. |
| robots.txt | ⏳ N/A yet | None served (site not live). |
| Legal pages | ⏳ N/A yet | None yet (site not live). |

**Net:** The two reputation gaps that matter most right now are that the site **isn't live with real content** and it has **no search presence**. The email side is in better shape than the old domain (SPF + MX already exist) — only DMARC is missing.

---

## Priority Actions

### 1. High — Point the domain at the real site and confirm HTTPS
- Move `metrislens.com` off the Namecheap parking page to your actual host. If you stay on Vercel, set the apex `A`/`ALIAS` and `www` `CNAME` per Vercel's instructions and let it auto-provision the Let's Encrypt certificate.
- Confirm the site loads over HTTPS at both `https://metrislens.com` and `https://www.metrislens.com`, with a redirect from one to the other (pick a canonical host).

### 2. High — Add a DMARC record
SPF already exists, so you only need DMARC. Add a TXT record at `_dmarc.metrislens.com`. Start in monitor mode:

```
v=DMARC1; p=none; rua=mailto:dmarc@metrislens.com
```

- `p=none` observes without affecting delivery; tighten to `quarantine`/`reject` later once you've confirmed nothing legitimate is failing.
- If you later send mail from a real provider (e.g. Google Workspace, a transactional service), add that provider's `include:` to the SPF record and set up DKIM with the selector they give you.
- If you decide the domain should send **no** mail at all, the alternative is to remove forwarding and publish explicit null records (`v=spf1 -all` and a `p=reject` DMARC). Don't do this while forwarding is in use.

### 3. High — Get the site indexed
- Verify there is **no** `noindex` meta tag or `X-Robots-Tag: noindex` header anywhere on the live site.
- Register the site with **Google Search Console** and **Bing Webmaster Tools**.
- Create and submit an XML sitemap (`https://metrislens.com/sitemap.xml`).
- Ensure navigation uses standard crawlable `<a href>` links.
- A real, crawlable, indexed site is the single strongest signal that distinguishes an established property from a freshly registered one.

### 4. Medium — Serve a robots.txt
Place a permissive `robots.txt` at the site root:

```
User-agent: *
Allow: /
Sitemap: https://metrislens.com/sitemap.xml
```

### 5. Medium — Add standard legal pages
- A **Privacy Policy** (covering analytics/cookies at minimum).
- A **Terms of Use**.
- Keep any investment/financial disclaimer you carried over from the previous site.

### 6. Medium — Submit for categorisation across the major URL-filtering vendors
This is the direct "get me unblocked / get me discovered" step. Submitting to all of them builds broad reputation rather than fixing only the one firewall in front of you:

| Vendor | Submission portal |
|--------|-------------------|
| Forcepoint (your company's filter) | `sitereview.forcepoint.com` |
| Palo Alto Networks | `urlfiltering.paloaltonetworks.com` |
| Zscaler | `sitereview.zscaler.com` |
| Symantec / Broadcom (WebPulse) | `sitereview.bluecoat.com` |
| McAfee / Trellix (TrustedSource) | `trustedsource.org` |

Submit only **after** the site is live with real content and legal pages — an empty or parked page will get categorised as exactly that.

---

## A Realistic Note on Timing

Doing all of the above stacks the odds in your favour, but be aware: **domain age itself is a factor** these filters weight, independent of any signal you control. A domain registered very recently can still land in the "newly registered" bucket for its first weeks regardless of how complete its configuration is — the signals above shorten and soften that window, they don't always eliminate it. The Forcepoint re-categorisation request is what actually clears the block fastest; the rest is what keeps it from recurring and prevents other vendors' filters from flagging you.

---

## Optional Aside — Brand-name proximity

Not a firewall issue, but worth knowing: the name sits close to several existing entities — **Metrasens** (`metrasens.com`, a detection/security-tech company), **Metalenz** (`metalenz.com`), and **metrisense.com** (currently listed for sale). This can create search-result confusion and make early SEO harder, since engines may associate or disambiguate against those established names. Worth a quick check that it doesn't clash with your positioning before you commit fully.
