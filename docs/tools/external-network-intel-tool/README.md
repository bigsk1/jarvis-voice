# External Network Intelligence

`external_network_intel` passively profiles a public IP address or domain. It is
intended for questions such as "what is this blocked IP?" and "who owns this
address?" without scanning the target or connecting to its ports.

## Data sources

For public IPs, a full lookup combines:

- RDAP registration and ownership from [ARIN](https://www.arin.net/resources/registry/whois/rdap/)
- current routed prefix and origin ASN from [RIPEstat](https://stat.ripe.net/docs/data-api/api-endpoints/network-info.html)
- PTR and bounded forward confirmation through [Google DNS over HTTPS](https://developers.google.com/speed/public-dns/docs/doh/json)
- passive hostnames, observed ports, CPEs, and vulnerability identifiers from [Shodan InternetDB](https://internetdb.shodan.io/)
- official Google Cloud, AWS, or Cloudflare published ranges when registry ownership identifies one of those providers
- optional reputation metadata from [AbuseIPDB](https://docs.abuseipdb.com/)

Domain lookups use IANA's RDAP bootstrap plus bounded A, AAAA, CNAME, MX, NS,
and TXT queries. Reputation lookup currently applies only to public IPs.

## AbuseIPDB setup

Set the optional key in the active mode's ignored environment file:

```dotenv
ABUSEIPDB_API_KEY=replace-with-your-key
```

Jarvis calls the fixed HTTPS API endpoint and sends the credential only in the
`Key` request header. It never puts the key in query parameters, tool output, or
follow-up context. Without a key, the rest of the lookup still works and the
AbuseIPDB source is reported as `not_configured`.

## Proxy and safety behavior

All provider requests use Jarvis's shared `http_client` with
`proxy_policy: prefer`: `LOCAL_PROXY`, then `LOCAL_PROXY2`, then direct fallback.
Only fixed HTTPS provider endpoints are contacted. Private, loopback, link-local,
reserved, multicast, and other non-global IPs are classified locally and are not
sent to public providers. Local, test, and onion domain suffixes are rejected.

The policy is set in `skills/external_network_intel.tool.json`. Jarvis supports
these manifest values:

| Policy | External network behavior |
|--------|---------------------------|
| `inherit` | Preserve the lookup code's requested proxy behavior. |
| `off` | Force direct access and suppress configured proxy variables. |
| `prefer` | Try `LOCAL_PROXY`, then `LOCAL_PROXY2`, then permit direct fallback. This tool's default. |
| `require` | Try only the configured proxy chain and never intentionally connect directly. Fail immediately if no proxy is configured. |

There is no `strict` policy value; `require` is the proxy-only, fail-closed mode.
If both proxies fail under `require`, provider requests fail without a direct
attempt. Because the tool isolates provider failures, it may return a partial
result with source errors rather than terminating the entire tool process.

Redirects are followed manually and only to HTTPS destinations. Authenticated
requests cannot redirect to another origin, preventing the AbuseIPDB `Key`
header from being forwarded to another host.

The tool is passive. Shodan InternetDB results are a periodic passive snapshot,
not a scan performed by Jarvis. Provider strings and reputation data are treated
as untrusted evidence and raw AbuseIPDB report comments are intentionally omitted.

## Example

```json
{
  "target": "35.190.88.7",
  "direction": "outbound",
  "destination_port": 443,
  "event_timestamp": "2026-08-21T09:15:00-07:00"
}
```

The result separates registry ownership, routing, DNS/service associations, and
reputation. It may support a benign-service hypothesis, but it cannot identify
which local process opened a connection. Correlate direction, port, TLS SNI or
hostname, device logs, and process telemetry before deciding whether a specific
firewall event was malicious or safe.
