# JSON Schemas

This directory contains JSON Schema files for the static data in this repository.

## Files

- `calendar.schema.json`: yearly oil price adjustment calendar, for `data/calendar/{year}.json`.
- `calendar-latest.schema.json`: latest calendar pointer, for `data/calendar/latest.json`.
- `source-sites.schema.json`: official provincial source registry, for `data/sources/provinces.json`.
- `prices.schema.json`: full oil price snapshot after one adjustment window, for `data/prices/{year}/{date}.json`.
- `price-summary.schema.json`: completeness summary paired with each price snapshot.
- `price-latest.schema.json`: latest price snapshot pointer, for `data/prices/latest.json`.
- `region-zones.schema.json`: province-level price zone metadata, for `data/regions/{province}.json`.
- `region-index.schema.json`: normalized region-to-price-zone lookup index, for `data/regions/regions.json`.

Run `python -m oilprice.cli validate-json` to validate all controlled JSON files against
these schemas and the repository's cross-file semantic invariants.

## Price Snapshot Shape

Price snapshots are grouped by province first, then by price zone:

```json
{
  "province_code": "510000",
  "province_name": "四川省",
  "sources": [
    {
      "name": "四川省发改委",
      "url": "https://example.com"
    }
  ],
  "zones": [
    {
      "zone_code": "sichuan-1",
      "zone_name": "一价区",
      "items": {
        "89": 7.13,
        "92": 7.62,
        "95": 8.14,
        "0": 7.24
      },
      "missing_products": []
    }
  ]
}
```

If an official source does not publish a product price, omit it from `items` and list it in `missing_products`.

Generated source provenance identifies the parser with an adapter-scoped version such as
`beijing-v1` or `shaanxi-v2`, so one adapter can evolve without invalidating every parser.

## Publication Status

Each price summary and `data/prices/latest.json` declares a coverage `status`:

- `complete`: every province in `data/sources/provinces.json` is present.
- `partial`: the snapshot is real and publishable, but `provinces_missing` is non-empty.

`latest` means the newest observed price snapshot, not the newest complete snapshot. Consumers
that require nationwide coverage must check `status == "complete"` before using it.

All source URLs use the strict `http-uri` format: only credential-free HTTP(S) URLs with a
valid host and port are accepted.
